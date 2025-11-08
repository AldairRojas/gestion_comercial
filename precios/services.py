from django.utils import timezone
from django.db.models import Q, Prefetch
from decimal import Decimal
from typing import List, Dict, Optional, Tuple

from .models import ListaPrecio, PrecioArticulo, ReglaPrecio, CombinacionProducto, DescuentoProveedor
from inventario.models import Articulo


class PrecioService:
    """
    Gestiona toda la lógica de negocio para el cálculo de precios.
    Implementa el cálculo jerárquico: precio base → canal → escala → monto → combinación → validación de costo → descuentos especiales
    [cite: 25, 28, 30]
    """

    def __init__(self, empresa_id, sucursal_id, canal, cliente_id=None):
        self.empresa_id = empresa_id
        self.sucursal_id = sucursal_id
        self.canal = canal
        self.cliente_id = cliente_id
        self._lista_vigente_cache = None

    def obtener_lista_vigente(self):
        """
        Encuentra la lista de precios activa y vigente.
        Optimizado con select_related para reducir consultas.
        [cite: 17, 30, 37]
        """
        if self._lista_vigente_cache is not None:
            return self._lista_vigente_cache
            
        hoy = timezone.now().date()
        
        q_vigencia = Q(estado=ListaPrecio.EstadoLista.ACTIVA) & \
                     Q(fecha_inicio__lte=hoy) & \
                     (Q(fecha_fin__gte=hoy) | Q(fecha_fin__isnull=True))

        q_canal = Q(canal_venta=ListaPrecio.CanalVenta.TODOS) | Q(canal_venta=self.canal)
        
        # 1. Intenta buscar lista específica de la SUCURSAL
        lista = ListaPrecio.objects.filter(
            q_vigencia & q_canal,
            empresa_id=self.empresa_id,
            sucursal_id=self.sucursal_id
        ).select_related('empresa', 'sucursal').order_by('-fecha_inicio').first() 

        # 2. Si no hay de sucursal, busca lista general de la EMPRESA
        if not lista:
            lista = ListaPrecio.objects.filter(
                q_vigencia & q_canal,
                empresa_id=self.empresa_id,
                sucursal_id__isnull=True 
            ).select_related('empresa').order_by('-fecha_inicio').first()
        
        self._lista_vigente_cache = lista
        return lista

    def calcular_precio(
        self, 
        articulo_id: int, 
        cantidad: int, 
        monto_pedido: Decimal = Decimal('0.00'),
        articulos_pedido: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Método principal que calcula el precio final de un artículo.
        Implementa el cálculo jerárquico según especificación.
        [cite: 25, 30]
        
        Args:
            articulo_id: ID del artículo
            cantidad: Cantidad del artículo en el pedido
            monto_pedido: Monto total del pedido
            articulos_pedido: Lista de artículos en el pedido para validar combinaciones.
                            Formato: [{'articulo_id': int, 'cantidad': int}, ...]
        
        Returns:
            Dict con precio_base, precio_final, reglas_aplicadas, autorizado_bajo_costo
        """
        
        # Validar artículo
        try:
            articulo = Articulo.objects.select_related('grupo', 'linea').get(pk=articulo_id)
        except Articulo.DoesNotExist:
            return {"error": "Artículo no encontrado."}

        # Obtener lista vigente
        lista_activa = self.obtener_lista_vigente()
        if not lista_activa:
            return {"error": "No se encontró lista de precios vigente para la empresa, sucursal y canal especificados."}

        # 1. PRECIO BASE [cite: 25]
        try:
            precio_base_obj = PrecioArticulo.objects.select_related('articulo', 'lista_precio').get(
                lista_precio=lista_activa,
                articulo=articulo
            )
            precio_final = precio_base_obj.precio_base
            autorizado_costo = precio_base_obj.autorizado_bajo_costo
        except PrecioArticulo.DoesNotExist:
            return {"error": f"Artículo '{articulo.nombre}' no encontrado en la lista de precios '{lista_activa.nombre}'."}

        # Normalizar articulos_pedido
        if articulos_pedido is None:
            articulos_pedido = [{'articulo_id': articulo_id, 'cantidad': cantidad}]

        # 2. OBTENER REGLAS ORDENADAS POR PRIORIDAD [cite: 25]
        reglas = self._obtener_reglas_aplicables(lista_activa, articulo)
        
        # 3. APLICAR REGLAS EN ORDEN JERÁRQUICO [cite: 25]
        reglas_aplicadas_log = []
        detalles_reglas = []
        
        for regla in reglas:
            precio_anterior = precio_final
            precio_actualizado, regla_fue_aplicada, motivo = self._aplicar_regla(
                regla, precio_final, articulo, cantidad, monto_pedido, articulos_pedido, lista_activa
            )
            
            if regla_fue_aplicada:
                precio_final = precio_actualizado
                reglas_aplicadas_log.append(regla.get_tipo_regla_display())
                detalles_reglas.append({
                    'tipo': regla.get_tipo_regla_display(),
                    'prioridad': regla.prioridad,
                    'precio_antes': precio_anterior,
                    'precio_despues': precio_actualizado,
                    'motivo': motivo
                })

        # 4. VALIDACIÓN DE COSTO [cite: 21, 30]
        precio_final, autorizado_costo, descuento_proveedor_aplicado = self._validar_costo(
            articulo, precio_base_obj.precio_base, precio_final, autorizado_costo, 
            reglas_aplicadas_log, lista_activa, cantidad, monto_pedido
        )

        return {
            "precio_base": precio_base_obj.precio_base,
            "precio_final": precio_final.quantize(Decimal('0.01')),
            "reglas_aplicadas": reglas_aplicadas_log,
            "detalles_reglas": detalles_reglas,
            "autorizado_bajo_costo": autorizado_costo,
            "descuento_proveedor_aplicado": descuento_proveedor_aplicado
        }

    def _obtener_reglas_aplicables(self, lista_precio: ListaPrecio, articulo: Articulo):
        """
        Obtiene las reglas aplicables al artículo, optimizadas con prefetch.
        [cite: 37]
        """
        q_alcance = (
            Q(aplica_articulo=articulo) |
            Q(aplica_grupo=articulo.grupo) |
            Q(aplica_linea=articulo.linea) |
            (Q(aplica_articulo__isnull=True) & Q(aplica_grupo__isnull=True) & Q(aplica_linea__isnull=True))
        )
        
        return ReglaPrecio.objects.filter(
            lista_precio=lista_precio
        ).filter(q_alcance).select_related(
            'aplica_articulo', 'aplica_grupo', 'aplica_linea', 'combinacion_requerida'
        ).prefetch_related(
            'combinacion_requerida__articulos',
            'combinacion_requerida__grupos_articulo',
            'combinacion_requerida__lineas_articulo'
        ).order_by('prioridad')

    def _aplicar_regla(
        self, 
        regla: ReglaPrecio, 
        precio_actual: Decimal, 
        articulo: Articulo, 
        cantidad: int, 
        monto_pedido: Decimal,
        articulos_pedido: List[Dict],
        lista_precio: ListaPrecio
    ) -> Tuple[Decimal, bool, str]:
        """
        Aplica una regla específica según su tipo.
        Retorna: (nuevo_precio, fue_aplicada, motivo)
        [cite: 30]
        """
        regla_aplicada = False
        nuevo_precio = precio_actual
        motivo = ""

        # Validar alcance de la regla
        if not self._validar_alcance_regla(regla, articulo):
            return nuevo_precio, False, "Regla no aplica al artículo"

        # CANAL DE VENTA (debe aplicarse primero después del precio base)
        if regla.tipo_regla == ReglaPrecio.TipoRegla.CANAL_VENTA:
            if regla.canal_venta_especifico == self.canal:
                regla_aplicada = True
                motivo = f"Canal de venta coincide: {self.canal}"

        # ESCALA POR UNIDADES
        elif regla.tipo_regla == ReglaPrecio.TipoRegla.ESCALA_UNIDADES:
            min_qty = regla.cantidad_minima or 1
            max_qty = regla.cantidad_maxima or float('inf')
            
            if min_qty <= cantidad <= max_qty:
                regla_aplicada = True
                motivo = f"Cantidad ({cantidad}) dentro del rango [{min_qty}, {max_qty if max_qty != float('inf') else 'inf'}]"

        # MONTO TOTAL DEL PEDIDO
        elif regla.tipo_regla == ReglaPrecio.TipoRegla.MONTO_PEDIDO:
            if regla.monto_minimo_pedido and monto_pedido >= regla.monto_minimo_pedido:
                regla_aplicada = True
                motivo = f"Monto pedido (${monto_pedido}) >= mínimo requerido (${regla.monto_minimo_pedido})"

        # COMBINACIÓN DE PRODUCTOS
        elif regla.tipo_regla == ReglaPrecio.TipoRegla.COMBINACION:
            if regla.combinacion_requerida:
                if self._validar_combinacion_productos(regla.combinacion_requerida, articulos_pedido):
                    regla_aplicada = True
                    motivo = f"Combinación '{regla.combinacion_requerida.nombre}' válida en el pedido"

        # DESCUENTO PROVEEDOR (siempre aplicable si se cumple el alcance)
        elif regla.tipo_regla == ReglaPrecio.TipoRegla.DESCUENTO_PROVEEDOR:
            regla_aplicada = True
            motivo = "Descuento de proveedor habilitado"

        # Aplicar resultado de la regla
        if regla_aplicada:
            if regla.precio_fijo_resultado is not None:
                nuevo_precio = regla.precio_fijo_resultado
            elif regla.descuento_porcentaje is not None:
                descuento = (regla.descuento_porcentaje / Decimal('100.00'))
                nuevo_precio = precio_actual * (Decimal('1.00') - descuento)
                nuevo_precio = max(nuevo_precio, Decimal('0.00'))  # No permitir precios negativos

        return nuevo_precio, regla_aplicada, motivo

    def _validar_alcance_regla(self, regla: ReglaPrecio, articulo: Articulo) -> bool:
        """
        Valida si la regla aplica al artículo según su alcance.
        """
        # Si no tiene alcance definido, aplica a todos
        if not regla.aplica_articulo and not regla.aplica_grupo and not regla.aplica_linea:
            return True
        
        # Validar por artículo específico
        if regla.aplica_articulo and regla.aplica_articulo == articulo:
            return True
        
        # Validar por grupo
        if regla.aplica_grupo and articulo.grupo and regla.aplica_grupo == articulo.grupo:
            return True
        
        # Validar por línea
        if regla.aplica_linea and articulo.linea and regla.aplica_linea == articulo.linea:
            return True
        
        return False

    def _validar_combinacion_productos(self, combinacion: CombinacionProducto, articulos_pedido: List[Dict]) -> bool:
        """
        Valida si todos los productos de la combinación están presentes en el pedido.
        [cite: 26]
        """
        # Obtener IDs de artículos en el pedido
        ids_articulos_pedido = {item['articulo_id'] for item in articulos_pedido}
        
        # Verificar artículos específicos
        articulos_combinacion = combinacion.articulos.all()
        if articulos_combinacion.exists():
            ids_articulos_combinacion = set(articulos_combinacion.values_list('id', flat=True))
            if not ids_articulos_combinacion.issubset(ids_articulos_pedido):
                return False
        
        # Verificar grupos
        grupos_combinacion = combinacion.grupos_articulo.all()
        if grupos_combinacion.exists():
            # Obtener todos los artículos del pedido con sus grupos
            articulos_con_grupo = Articulo.objects.filter(
                id__in=ids_articulos_pedido,
                grupo__in=grupos_combinacion
            ).values_list('grupo_id', flat=True)
            
            grupos_en_pedido = set(articulos_con_grupo)
            grupos_requeridos = set(grupos_combinacion.values_list('id', flat=True))
            
            if not grupos_requeridos.issubset(grupos_en_pedido):
                return False
        
        # Verificar líneas
        lineas_combinacion = combinacion.lineas_articulo.all()
        if lineas_combinacion.exists():
            articulos_con_linea = Articulo.objects.filter(
                id__in=ids_articulos_pedido,
                linea__in=lineas_combinacion
            ).values_list('linea_id', flat=True)
            
            lineas_en_pedido = set(articulos_con_linea)
            lineas_requeridas = set(lineas_combinacion.values_list('id', flat=True))
            
            if not lineas_requeridas.issubset(lineas_en_pedido):
                return False
        
        # Si la combinación tiene criterios y todos se cumplen, es válida
        if articulos_combinacion.exists() or grupos_combinacion.exists() or lineas_combinacion.exists():
            return True
        
        # Si no tiene criterios, no es válida
        return False

    def _validar_costo(
        self, 
        articulo: Articulo, 
        precio_base: Decimal,
        precio_final: Decimal, 
        autorizado_costo: bool, 
        reglas_aplicadas: List[str],
        lista_precio: ListaPrecio,
        cantidad: int,
        monto_pedido: Decimal
    ) -> Tuple[Decimal, bool, bool]:
        """
        Valida que el precio final no sea inferior al costo, excepto cuando está autorizado.
        Registra descuentos de proveedor cuando corresponde.
        [cite: 20, 21, 30]
        """
        descuento_proveedor_aplicado = False
        
        # Si ya estaba autorizado en el precio base, lo respetamos
        if autorizado_costo:
            return precio_final, True, descuento_proveedor_aplicado

        # Si el precio final es menor al costo
        if precio_final < articulo.ultimo_costo:
            # Verificamos si se aplicó un descuento de proveedor
            tiene_descuento_proveedor = any(
                "Descuento Proveedor" in regla for regla in reglas_aplicadas
            )
            
            if tiene_descuento_proveedor:
                # Calcular porcentaje de descuento
                descuento_porcentaje = ((precio_base - precio_final) / precio_base) * Decimal('100.00')
                
                # Validar que esté en el rango permitido (50% a 70%)
                if 50 <= descuento_porcentaje <= 70:
                    # Registrar descuento de proveedor [cite: 21, 30]
                    self._registrar_descuento_proveedor(
                        articulo=articulo,
                        lista_precio=lista_precio,
                        precio_base=precio_base,
                        precio_final=precio_final,
                        descuento_porcentaje=descuento_porcentaje,
                        cantidad=cantidad,
                        monto_pedido=monto_pedido
                    )
                    descuento_proveedor_aplicado = True
                    return precio_final, True, descuento_proveedor_aplicado
                else:
                    # Descuento fuera del rango permitido, revertir al costo
                    return articulo.ultimo_costo, False, False
            else:
                # No está autorizado, revertir al costo
                return articulo.ultimo_costo, False, False
            
        return precio_final, autorizado_costo, descuento_proveedor_aplicado

    def _registrar_descuento_proveedor(
        self,
        articulo: Articulo,
        lista_precio: ListaPrecio,
        precio_base: Decimal,
        precio_final: Decimal,
        descuento_porcentaje: Decimal,
        cantidad: int,
        monto_pedido: Decimal
    ):
        """
        Registra un descuento de proveedor en la base de datos para auditoría.
        [cite: 30]
        """
        try:
            DescuentoProveedor.objects.create(
                articulo=articulo,
                lista_precio=lista_precio,
                precio_base=precio_base,
                precio_final=precio_final,
                descuento_porcentaje=descuento_porcentaje,
                costo_articulo=articulo.ultimo_costo,
                canal_venta=self.canal,
                cantidad=cantidad,
                monto_pedido=monto_pedido,
                autorizado_por=getattr(self, 'usuario_actual', 'Sistema'),
                notas=f"Descuento automático aplicado por regla de precio"
            )
        except Exception as e:
            # Log del error pero no fallar la operación principal
            print(f"Error al registrar descuento de proveedor: {e}")

    def calcular_precios_pedido(self, articulos_pedido: List[Dict], monto_pedido_total: Decimal) -> Dict:
        """
        Calcula los precios para todos los artículos de un pedido.
        Útil para calcular el monto total y aplicar reglas de combinación correctamente.
        [cite: 30]
        
        Args:
            articulos_pedido: Lista de artículos con formato [{'articulo_id': int, 'cantidad': int}, ...]
            monto_pedido_total: Monto total del pedido
        
        Returns:
            Dict con resultados por artículo y resumen
        """
        resultados = {}
        total_pedido = Decimal('0.00')
        
        for item in articulos_pedido:
            resultado = self.calcular_precio(
                articulo_id=item['articulo_id'],
                cantidad=item['cantidad'],
                monto_pedido=monto_pedido_total,
                articulos_pedido=articulos_pedido
            )
            
            if 'error' not in resultado:
                subtotal = resultado['precio_final'] * Decimal(str(item['cantidad']))
                total_pedido += subtotal
                resultado['subtotal'] = subtotal
            
            resultados[item['articulo_id']] = resultado
        
        return {
            'articulos': resultados,
            'total_pedido': total_pedido,
            'monto_pedido_original': monto_pedido_total
        }

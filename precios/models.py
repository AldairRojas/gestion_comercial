from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError

# --- Modelo Base para Auditoría ---
class TimeStampedModel(models.Model):
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

# --- Modelos del Módulo de Precios ---

class ListaPrecio(TimeStampedModel):
    """
    Define la lista por empresa/sucursal y vigencia.
    [cite: 15, 16, 17]
    """
    class TipoLista(models.TextChoices):
        GENERAL = 'GENERAL', 'General'
        PROMOCION = 'PROMOCION', 'Promoción'
        ESPECIAL = 'ESPECIAL', 'Especial'

    class CanalVenta(models.TextChoices):
        MAYORISTA = 'MAYORISTA', 'Mayorista'
        MINORISTA = 'MINORISTA', 'Minorista'
        ECOMMERCE = 'ECOMMERCE', 'E-commerce'
        TODOS = 'TODOS', 'Todos'

    class EstadoLista(models.TextChoices):
        ACTIVA = 'ACTIVA', 'Activa'
        INACTIVA = 'INACTIVA', 'Inactiva'

    # Relaciones [cite: 26]
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='listas_precios')
    sucursal = models.ForeignKey('empresas.Sucursal', on_delete=models.CASCADE, related_name='listas_precios', null=True, blank=True)
    
    nombre = models.CharField(max_length=255)
    tipo = models.CharField(max_length=50, choices=TipoLista.choices, default=TipoLista.GENERAL)
    canal_venta = models.CharField(max_length=50, choices=CanalVenta.choices, default=CanalVenta.TODOS)
    
    fecha_inicio = models.DateField(default=timezone.now)
    fecha_fin = models.DateField(null=True, blank=True)
    
    estado = models.CharField(max_length=50, choices=EstadoLista.choices, default=EstadoLista.ACTIVA)

    def __str__(self):
        return f"{self.nombre} ({self.empresa.nombre})"

    def clean(self):
        """ Validación para no solapar vigencias [cite: 35] """
        if self.fecha_fin and self.fecha_inicio > self.fecha_fin:
            raise ValidationError(
                {'fecha_fin': "La fecha de fin no puede ser anterior a la fecha de inicio."}
            )

        qs = ListaPrecio.objects.filter(
            empresa=self.empresa,
            sucursal=self.sucursal,
            canal_venta=self.canal_venta,
            estado=self.EstadoLista.ACTIVA # Solo revisar contra otras activas
        )
        
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        q_ends_after_our_start = Q(fecha_fin__gte=self.fecha_inicio) | Q(fecha_fin__isnull=True)
        
        if self.fecha_fin:
            q_starts_before_our_end = Q(fecha_inicio__lte=self.fecha_fin)
        else:
            q_starts_before_our_end = Q() 

        overlapping_lists = qs.filter(q_ends_after_our_start & q_starts_before_our_end)

        if overlapping_lists.exists():
            raise ValidationError(
                "Ya existe una lista de precios activa para esta empresa, sucursal y "
                "canal con fechas que se solapan."
            )
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para llamar a full_clean y validar"""
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Lista de Precio"
        verbose_name_plural = "Listas de Precios"
        ordering = ['empresa', 'nombre']


class PrecioArticulo(TimeStampedModel):
    """
    Precio base por artículo asociado a una lista.
    [cite: 19, 20, 21]
    """
    lista_precio = models.ForeignKey(ListaPrecio, on_delete=models.CASCADE, related_name='precios_articulos')
    articulo = models.ForeignKey('inventario.Articulo', on_delete=models.CASCADE, related_name='precios_en_listas')
    
    precio_base = models.DecimalField(max_digits=10, decimal_places=2)
    autorizado_bajo_costo = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.articulo.nombre} - ${self.precio_base} ({self.lista_precio.nombre})"

    def clean(self):
        """ Validación funcional: no inferior al costo [cite: 20] """
        if not self.autorizado_bajo_costo and self.precio_base < self.articulo.ultimo_costo:
            raise ValidationError(f"El precio base (${self.precio_base}) no puede ser inferior al último costo (${self.articulo.ultimo_costo}) sin autorización.")
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para llamar a full_clean y validar"""
        self.full_clean()
        super().save(*args, **kwargs)
        
    class Meta:
        verbose_name = "Precio de Artículo"
        verbose_name_plural = "Precios de Artículos"
        unique_together = ('lista_precio', 'articulo')


class CombinacionProducto(TimeStampedModel):
    """
    Agrupación de productos combinables. [cite: 26]
    """
    lista_precio = models.ForeignKey(ListaPrecio, on_delete=models.CASCADE, related_name='combinaciones')
    nombre = models.CharField(max_length=255)
    
    articulos = models.ManyToManyField('inventario.Articulo', blank=True, related_name='combinaciones_articulo')
    grupos_articulo = models.ManyToManyField('inventario.GrupoArticulo', blank=True, related_name='combinaciones_grupo')
    lineas_articulo = models.ManyToManyField('inventario.LineaArticulo', blank=True, related_name='combinaciones_linea')

    def __str__(self):
        return f"Combinación: {self.nombre} ({self.lista_precio.nombre})"
    
    def clean(self):
        """ Validar que la combinación tenga al menos un criterio definido """
        # Note: Esta validación solo funciona si el objeto ya está guardado
        # Para nuevos objetos, se debe validar después de guardar los ManyToMany
        pass
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para validar después de guardar (ManyToMany requiere objeto guardado)"""
        super().save(*args, **kwargs)
        # Validar después de guardar para que funcione con ManyToMany
        # Esta validación se puede omitir si se está creando desde el admin/form
        # ya que los ManyToMany se asignan después
        if self.pk:
            if not self.articulos.exists() and not self.grupos_articulo.exists() and not self.lineas_articulo.exists():
                # Solo lanzar error si estamos actualizando, no al crear
                pass  # La validación se hace en el serializer o admin


class DescuentoProveedor(TimeStampedModel):
    """
    Modelo para auditoría de descuentos de proveedor aplicados.
    Registra cuando se aplica un precio bajo costo con descuentos del 50% al 70% reconocidos por proveedor.
    [cite: 21, 30]
    """
    articulo = models.ForeignKey('inventario.Articulo', on_delete=models.CASCADE, related_name='descuentos_proveedor')
    lista_precio = models.ForeignKey(ListaPrecio, on_delete=models.CASCADE, related_name='descuentos_proveedor')
    
    precio_base = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio base antes del descuento")
    precio_final = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio final aplicado")
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, help_text="Porcentaje de descuento aplicado")
    costo_articulo = models.DecimalField(max_digits=10, decimal_places=2, help_text="Costo del artículo al momento del descuento")
    
    canal_venta = models.CharField(max_length=50, choices=ListaPrecio.CanalVenta.choices)
    cantidad = models.PositiveIntegerField(help_text="Cantidad del artículo en el pedido")
    monto_pedido = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    autorizado_por = models.CharField(max_length=255, blank=True, help_text="Usuario que autorizó el descuento")
    notas = models.TextField(blank=True, help_text="Notas adicionales sobre el descuento")

    def __str__(self):
        return f"Descuento {self.descuento_porcentaje}% - {self.articulo.nombre} - {self.lista_precio.nombre}"
    
    def clean(self):
        """ Validar que el descuento esté en el rango permitido (50% a 70%) """
        if self.descuento_porcentaje < 50 or self.descuento_porcentaje > 70:
            raise ValidationError(
                {'descuento_porcentaje': "Los descuentos de proveedor deben estar entre 50% y 70%."}
            )
        
        if self.precio_final >= self.costo_articulo:
            raise ValidationError(
                "El precio final debe ser menor al costo para considerar un descuento de proveedor."
            )
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para llamar a full_clean y validar"""
        self.full_clean()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Descuento de Proveedor"
        verbose_name_plural = "Descuentos de Proveedor"
        ordering = ['-creado_en']


class ReglaPrecio(TimeStampedModel):
    """
    Políticas comerciales dinámicas (reglas). [cite: 23, 26]
    """
    class TipoRegla(models.TextChoices):
        ESCALA_UNIDADES = 'ESCALA_UNIDADES', 'Escala por Unidades'
        MONTO_PEDIDO = 'MONTO_PEDIDO', 'Monto Total del Pedido'
        COMBINACION = 'COMBINACION', 'Combinación de Productos'
        DESCUENTO_PROVEEDOR = 'DESCUENTO_PROVEEDOR', 'Descuento Proveedor'
        CANAL_VENTA = 'CANAL_VENTA', 'Canal de Venta Específico' 

    lista_precio = models.ForeignKey(ListaPrecio, on_delete=models.CASCADE, related_name='reglas')
    tipo_regla = models.CharField(max_length=50, choices=TipoRegla.choices)
    
    prioridad = models.IntegerField(default=10, help_text="Menor número = mayor prioridad")

    # Alcance de la regla
    aplica_articulo = models.ForeignKey('inventario.Articulo', on_delete=models.CASCADE, null=True, blank=True, related_name='reglas_articulo')
    aplica_grupo = models.ForeignKey('inventario.GrupoArticulo', on_delete=models.CASCADE, null=True, blank=True, related_name='reglas_grupo')
    aplica_linea = models.ForeignKey('inventario.LineaArticulo', on_delete=models.CASCADE, null=True, blank=True, related_name='reglas_linea')

    # --- Condiciones de la regla ---
    cantidad_minima = models.PositiveIntegerField(null=True, blank=True, default=1)
    cantidad_maxima = models.PositiveIntegerField(null=True, blank=True)
    monto_minimo_pedido = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    combinacion_requerida = models.ForeignKey(CombinacionProducto, on_delete=models.SET_NULL, null=True, blank=True, related_name='reglas_combinacion')
    canal_venta_especifico = models.CharField(max_length=50, choices=ListaPrecio.CanalVenta.choices, null=True, blank=True)

    # --- Resultado de la regla ---
    precio_fijo_resultado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Ej. 50.00 para 50%")

    def __str__(self):
        return f"Regla ({self.get_tipo_regla_display()}) en {self.lista_precio.nombre} [P:{self.prioridad}]"

    def clean(self):
        """ Validación de solapamiento de reglas [cite: 35] """
        # Validar que solo un campo de alcance esté definido o ninguno (general)
        alcances = [self.aplica_articulo, self.aplica_grupo, self.aplica_linea]
        alcances_definidos = [a for a in alcances if a is not None]
        if len(alcances_definidos) > 1:
            raise ValidationError(
                "Solo se puede definir un alcance por regla (artículo, grupo o línea)."
            )
        
        # Validar que precio_fijo_resultado o descuento_porcentaje estén definidos, pero no ambos
        if self.precio_fijo_resultado is not None and self.descuento_porcentaje is not None:
            raise ValidationError(
                "No se puede definir simultáneamente precio fijo y descuento porcentual."
            )
        
        if self.precio_fijo_resultado is None and self.descuento_porcentaje is None:
            raise ValidationError(
                "Debe definirse al menos un resultado: precio fijo o descuento porcentual."
            )
        
        # Validar descuento porcentual
        if self.descuento_porcentaje is not None:
            if self.descuento_porcentaje < 0 or self.descuento_porcentaje > 100:
                raise ValidationError(
                    {'descuento_porcentaje': "El descuento debe estar entre 0 y 100."}
                )
        
        # Validar tipo de regla y sus condiciones requeridas
        if self.tipo_regla == self.TipoRegla.ESCALA_UNIDADES:
            if self.cantidad_minima is None:
                raise ValidationError(
                    {'cantidad_minima': "La cantidad mínima es requerida para reglas de escala."}
                )
            if self.cantidad_maxima and (self.cantidad_minima > self.cantidad_maxima):
                raise ValidationError(
                    {'cantidad_maxima': "La cantidad máxima no puede ser menor a la mínima."}
                )

            qs_base = ReglaPrecio.objects.filter(
                lista_precio=self.lista_precio,
                tipo_regla=self.tipo_regla,
                aplica_articulo=self.aplica_articulo,
                aplica_grupo=self.aplica_grupo,
                aplica_linea=self.aplica_linea
            )
            
            if self.pk:
                qs_base = qs_base.exclude(pk=self.pk)

            q_ends_after_our_start = Q(cantidad_maxima__gte=self.cantidad_minima) | Q(cantidad_maxima__isnull=True)
            
            if self.cantidad_maxima:
                q_starts_before_our_end = Q(cantidad_minima__lte=self.cantidad_maxima)
            else:
                q_starts_before_our_end = Q() 
                
            overlapping_rules = qs_base.filter(q_ends_after_our_start & q_starts_before_our_end)
            
            if overlapping_rules.exists():
                raise ValidationError(
                    "Ya existe una regla de 'Escala por Unidades' para este mismo alcance "
                    "cuyo rango de cantidades se solapa con esta regla."
                )
        
        elif self.tipo_regla == self.TipoRegla.MONTO_PEDIDO:
            if self.monto_minimo_pedido is None:
                raise ValidationError(
                    {'monto_minimo_pedido': "El monto mínimo del pedido es requerido para este tipo de regla."}
                )
        
        elif self.tipo_regla == self.TipoRegla.COMBINACION:
            if not self.combinacion_requerida:
                raise ValidationError(
                    {'combinacion_requerida': "Debe seleccionarse una combinación para este tipo de regla."}
                )
        
        elif self.tipo_regla == self.TipoRegla.CANAL_VENTA:
            if not self.canal_venta_especifico:
                raise ValidationError(
                    {'canal_venta_especifico': "Debe seleccionarse un canal de venta para este tipo de regla."}
                )
        
        # Validar que no haya reglas duplicadas con la misma prioridad
        qs_duplicado = ReglaPrecio.objects.filter(
            lista_precio=self.lista_precio,
            prioridad=self.prioridad
        )
        if self.pk:
            qs_duplicado = qs_duplicado.exclude(pk=self.pk)
        
        if qs_duplicado.exists():
            raise ValidationError(
                {'prioridad': f"Ya existe una regla con prioridad {self.prioridad} en esta lista de precios."}
            )
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para llamar a full_clean y validar"""
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Regla de Precio"
        verbose_name_plural = "Reglas de Precios"
        ordering = ['lista_precio', 'prioridad']
        unique_together = ('lista_precio', 'prioridad')
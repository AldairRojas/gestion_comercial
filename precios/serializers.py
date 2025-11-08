from rest_framework import serializers
from decimal import Decimal
from .models import ListaPrecio, PrecioArticulo, ReglaPrecio, CombinacionProducto, DescuentoProveedor
from inventario.models import Articulo

# --- Serializers para CRUD (Administración) ---

class ListaPrecioSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListaPrecio
        fields = '__all__'
        read_only_fields = ('creado_en', 'actualizado_en')
    
    def validate(self, data):
        """Valida solapamiento de vigencias"""
        # La validación principal está en el modelo (clean method)
        # Aquí solo validamos fechas
        fecha_inicio = data.get('fecha_inicio')
        fecha_fin = data.get('fecha_fin')
        
        if fecha_fin and fecha_inicio and fecha_inicio > fecha_fin:
            raise serializers.ValidationError(
                {'fecha_fin': "La fecha de fin no puede ser anterior a la fecha de inicio."}
            )
        
        return data

class PrecioArticuloSerializer(serializers.ModelSerializer):
    articulo_nombre = serializers.CharField(source='articulo.nombre', read_only=True)
    lista_precio_nombre = serializers.CharField(source='lista_precio.nombre', read_only=True)
    
    class Meta:
        model = PrecioArticulo
        fields = '__all__'
        read_only_fields = ('creado_en', 'actualizado_en')
        
    def validate(self, data):
        """Valida que el precio base no sea inferior al costo sin autorización"""
        precio_base = data.get('precio_base')
        articulo = data.get('articulo')
        autorizado = data.get('autorizado_bajo_costo', False)
        
        if articulo and precio_base is not None:
            if not autorizado and precio_base < articulo.ultimo_costo:
                raise serializers.ValidationError(
                    f"El precio base (${precio_base}) no puede ser inferior al "
                    f"último costo (${articulo.ultimo_costo}) sin autorización."
                ) 
        
        return data

class ReglaPrecioSerializer(serializers.ModelSerializer):
    lista_precio_nombre = serializers.CharField(source='lista_precio.nombre', read_only=True)
    aplica_articulo_nombre = serializers.CharField(source='aplica_articulo.nombre', read_only=True)
    aplica_grupo_nombre = serializers.CharField(source='aplica_grupo.nombre', read_only=True)
    aplica_linea_nombre = serializers.CharField(source='aplica_linea.nombre', read_only=True)
    combinacion_nombre = serializers.CharField(source='combinacion_requerida.nombre', read_only=True)
    
    class Meta:
        model = ReglaPrecio
        fields = '__all__'
        read_only_fields = ('creado_en', 'actualizado_en')


class CombinacionProductoSerializer(serializers.ModelSerializer):
    lista_precio_nombre = serializers.CharField(source='lista_precio.nombre', read_only=True)
    
    class Meta:
        model = CombinacionProducto
        fields = '__all__'
        read_only_fields = ('creado_en', 'actualizado_en')
    
    def validate(self, data):
        """Validar que la combinación tenga al menos un criterio"""
        # Los ManyToMany se validan después de crear/actualizar el objeto
        return data
    
    def validate_articulos(self, value):
        """Validar artículos si están presentes"""
        return value
    
    def validate_grupos_articulo(self, value):
        """Validar grupos si están presentes"""
        return value
    
    def validate_lineas_articulo(self, value):
        """Validar líneas si están presentes"""
        return value


class DescuentoProveedorSerializer(serializers.ModelSerializer):
    articulo_nombre = serializers.CharField(source='articulo.nombre', read_only=True)
    lista_precio_nombre = serializers.CharField(source='lista_precio.nombre', read_only=True)
    
    class Meta:
        model = DescuentoProveedor
        fields = '__all__'
        read_only_fields = ('creado_en', 'actualizado_en')

# --- Serializers para el Endpoint de Cálculo [cite: 33] ---

class ArticuloPedidoSerializer(serializers.Serializer):
    """Serializer para artículos en un pedido (para validar combinaciones)"""
    articulo_id = serializers.IntegerField(required=True)
    cantidad = serializers.IntegerField(required=True, min_value=1)


class CalculoPrecioInputSerializer(serializers.Serializer):
    """
    Valida la request para el cálculo de precio.
    [cite: 32, 33]
    """
    empresa_id = serializers.IntegerField(required=True)
    sucursal_id = serializers.IntegerField(required=True, allow_null=True)
    articulo_id = serializers.IntegerField(required=True)
    canal = serializers.ChoiceField(choices=ListaPrecio.CanalVenta.choices, required=True)
    cantidad = serializers.IntegerField(required=True, min_value=1)
    monto_pedido = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal('0.00')
    )
    articulos_pedido = ArticuloPedidoSerializer(many=True, required=False, help_text="Lista completa de artículos del pedido para validar combinaciones")


class DetalleReglaSerializer(serializers.Serializer):
    """Serializer para detalles de reglas aplicadas"""
    tipo = serializers.CharField()
    prioridad = serializers.IntegerField()
    precio_antes = serializers.DecimalField(max_digits=10, decimal_places=2)
    precio_despues = serializers.DecimalField(max_digits=10, decimal_places=2)
    motivo = serializers.CharField()


class CalculoPrecioOutputSerializer(serializers.Serializer):
    """
    Formatea la respuesta del cálculo de precio. [cite: 33]
    """
    precio_base = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    precio_final = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    reglas_aplicadas = serializers.ListField(child=serializers.CharField(), required=False)
    detalles_reglas = DetalleReglaSerializer(many=True, required=False)
    autorizado_bajo_costo = serializers.BooleanField(required=False)
    descuento_proveedor_aplicado = serializers.BooleanField(required=False)
    error = serializers.CharField(required=False)
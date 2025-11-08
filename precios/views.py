from rest_framework import viewsets, status, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import transaction

# Modelos y Serializers
from .models import ListaPrecio, PrecioArticulo, ReglaPrecio, CombinacionProducto, DescuentoProveedor
from .services import PrecioService
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from .serializers import (
    ListaPrecioSerializer, PrecioArticuloSerializer, ReglaPrecioSerializer,
    CombinacionProductoSerializer, DescuentoProveedorSerializer,
    CalculoPrecioInputSerializer, CalculoPrecioOutputSerializer
)


# --- ViewSets para Administración (CRUD) ---

class ListaPrecioViewSet(viewsets.ModelViewSet):
    queryset = ListaPrecio.objects.all()
    serializer_class = ListaPrecioSerializer
    
    # --- AÑADE ESTAS LÍNEAS --- [cite: 752-755, 968]
    permission_classes = [IsAdminUser] # Solo Admin puede editar listas
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['empresa', 'sucursal', 'canal_venta', 'estado'] # Filtrar por
    search_fields = ['nombre'] # Buscar por
    ordering_fields = ['nombre', 'fecha_inicio'] # Ordenar por
    # ---------------------------

class ReglaPrecioViewSet(viewsets.ModelViewSet):
    queryset = ReglaPrecio.objects.all()
    serializer_class = ReglaPrecioSerializer
    
    # --- AÑADE ESTAS LÍNEAS ---
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['lista_precio', 'tipo_regla']
    search_fields = ['lista_precio__nombre']
    # ---------------------------

class PrecioArticuloViewSet(viewsets.ModelViewSet):
    queryset = PrecioArticulo.objects.all()
    serializer_class = PrecioArticuloSerializer
    
    # --- AÑADE ESTAS LÍNEAS ---
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['lista_precio', 'articulo', 'autorizado_bajo_costo']
    ordering_fields = ['precio_base']
    # ---------------------------

# --- Endpoint Principal de Cálculo ---
# [cite: 32, 33]

class CalculoPrecioView(APIView):
    """
    Endpoint para el cálculo de precio final.
    Permite calcular el precio de un artículo aplicando todas las reglas comerciales.
    [cite: 32, 33]
    """

    # Permitir a cualquier usuario autenticado calcular precios
    permission_classes = [IsAuthenticated]
    
    def post(self, request, *args, **kwargs):
        input_serializer = CalculoPrecioInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = input_serializer.validated_data
        
        try:
            # Usamos transaction.atomic para operaciones atómicas [cite: 37]
            with transaction.atomic():
                service = PrecioService(
                    empresa_id=data['empresa_id'],
                    sucursal_id=data.get('sucursal_id'),
                    canal=data['canal']
                )
                
                # Obtener articulos_pedido si están presentes
                articulos_pedido = data.get('articulos_pedido')
                if articulos_pedido:
                    articulos_pedido = [
                        {'articulo_id': item['articulo_id'], 'cantidad': item['cantidad']}
                        for item in articulos_pedido
                    ]
                
                resultado = service.calcular_precio(
                    articulo_id=data['articulo_id'],
                    cantidad=data['cantidad'],
                    monto_pedido=data.get('monto_pedido', 0),
                    articulos_pedido=articulos_pedido
                )

            # Validar si el servicio devolvió un error de negocio
            if "error" in resultado:
                output_serializer = CalculoPrecioOutputSerializer(data=resultado)
                output_serializer.is_valid()
                return Response(output_serializer.data, status=status.HTTP_400_BAD_REQUEST)

            # Devolver la respuesta exitosa
            output_serializer = CalculoPrecioOutputSerializer(data=resultado)
            output_serializer.is_valid(raise_exception=True) 
            return Response(output_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            # Captura de error general (ej. fallo de BD)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CombinacionProductoViewSet(viewsets.ModelViewSet):
    """ViewSet para administrar combinaciones de productos"""
    queryset = CombinacionProducto.objects.all()
    serializer_class = CombinacionProductoSerializer
    
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['lista_precio']
    search_fields = ['nombre']


class DescuentoProveedorViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet de solo lectura para consultar descuentos de proveedor (auditoría)"""
    queryset = DescuentoProveedor.objects.all()
    serializer_class = DescuentoProveedorSerializer
    
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['articulo', 'lista_precio', 'canal_venta']
    search_fields = ['articulo__nombre', 'autorizado_por']
    ordering_fields = ['creado_en', 'descuento_porcentaje']
    ordering = ['-creado_en']
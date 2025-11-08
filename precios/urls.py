from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Creamos un router para registrar los ViewSets de CRUD
router = DefaultRouter()
router.register(r'listas-precio', views.ListaPrecioViewSet, basename='listaprecio')
router.register(r'reglas-precio', views.ReglaPrecioViewSet, basename='reglaprecio')
router.register(r'precios-articulo', views.PrecioArticuloViewSet, basename='precioarticulo')
router.register(r'combinaciones', views.CombinacionProductoViewSet, basename='combinacionproducto')
router.register(r'descuentos-proveedor', views.DescuentoProveedorViewSet, basename='descuentoproveedor')

urlpatterns = [
    # URLs de los ViewSets (ej. /api/precios/listas-precio/)
    path('', include(router.urls)),
    
    # URL para el endpoint de cálculo
    path('calcular-precio/', views.CalculoPrecioView.as_view(), name='calcular-precio'),
]
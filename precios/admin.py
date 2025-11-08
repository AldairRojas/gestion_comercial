from django.contrib import admin
from .models import ListaPrecio, PrecioArticulo, ReglaPrecio, CombinacionProducto, DescuentoProveedor

@admin.register(ListaPrecio)
class ListaPrecioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'empresa', 'sucursal', 'canal_venta', 'fecha_inicio', 'fecha_fin', 'estado')
    list_filter = ('estado', 'canal_venta', 'empresa', 'tipo')
    search_fields = ('nombre', 'empresa__nombre')
    date_hierarchy = 'fecha_inicio'

@admin.register(PrecioArticulo)
class PrecioArticuloAdmin(admin.ModelAdmin):
    list_display = ('articulo', 'lista_precio', 'precio_base', 'autorizado_bajo_costo', 'creado_en')
    list_filter = ('lista_precio', 'autorizado_bajo_costo')
    search_fields = ('articulo__nombre', 'lista_precio__nombre')
    raw_id_fields = ('articulo', 'lista_precio')

@admin.register(ReglaPrecio)
class ReglaPrecioAdmin(admin.ModelAdmin):
    list_display = ('lista_precio', 'tipo_regla', 'prioridad', 'aplica_articulo', 'aplica_grupo', 'aplica_linea', 'cantidad_minima', 'descuento_porcentaje', 'precio_fijo_resultado')
    list_filter = ('tipo_regla', 'lista_precio')
    search_fields = ('lista_precio__nombre',)
    raw_id_fields = ('aplica_articulo', 'aplica_grupo', 'aplica_linea', 'combinacion_requerida')

@admin.register(CombinacionProducto)
class CombinacionProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'lista_precio', 'creado_en')
    list_filter = ('lista_precio',)
    search_fields = ('nombre', 'lista_precio__nombre')
    filter_horizontal = ('articulos', 'grupos_articulo', 'lineas_articulo')

@admin.register(DescuentoProveedor)
class DescuentoProveedorAdmin(admin.ModelAdmin):
    list_display = ('articulo', 'lista_precio', 'descuento_porcentaje', 'precio_base', 'precio_final', 'costo_articulo', 'canal_venta', 'creado_en')
    list_filter = ('canal_venta', 'lista_precio', 'creado_en')
    search_fields = ('articulo__nombre', 'autorizado_por')
    readonly_fields = ('creado_en', 'actualizado_en')
    date_hierarchy = 'creado_en'
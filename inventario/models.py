from django.db import models

class GrupoArticulo(models.Model):
    nombre = models.CharField(max_length=100)
    
    def __str__(self):
        return self.nombre

class LineaArticulo(models.Model):
    nombre = models.CharField(max_length=100)
    
    def __str__(self):
        return self.nombre

class Articulo(models.Model):
    nombre = models.CharField(max_length=100)
    # Este campo es crucial para la validación [cite: 20]
    ultimo_costo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    grupo = models.ForeignKey(GrupoArticulo, on_delete=models.SET_NULL, null=True, blank=True)
    linea = models.ForeignKey(LineaArticulo, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.nombre
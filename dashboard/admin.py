from django.contrib import admin

from . import models

admin.site.register(models.DataSource)
admin.site.register(models.MonthlyVolume)
admin.site.register(models.CppiRecord)
admin.site.register(models.UnctadValue)
admin.site.register(models.PortCallDaily)
admin.site.register(models.WeatherPoint)
admin.site.register(models.AisPosition)
admin.site.register(models.Insight)

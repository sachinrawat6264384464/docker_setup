from django.contrib import admin
from .models import Country, State, District, City, Pincode, Area


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ['name', 'code']
    search_fields = ['name', 'code']


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'country']
    list_filter = ['country']
    search_fields = ['name', 'code']
    ordering = ['name']


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ['name', 'state']
    list_filter = ['state__country', 'state']
    search_fields = ['name', 'state__name']
    ordering = ['state__name', 'name']
    autocomplete_fields = ['state']


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ['name', 'district', 'get_state']
    list_filter = ['district__state']
    search_fields = ['name', 'district__name', 'district__state__name']
    ordering = ['district__state__name', 'district__name', 'name']
    autocomplete_fields = ['district']

    @admin.display(description='State', ordering='district__state__name')
    def get_state(self, obj):
        return obj.district.state.name


@admin.register(Pincode)
class PincodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'city', 'get_district', 'get_state']
    list_filter = ['city__district__state']
    search_fields = ['code', 'city__name', 'city__district__name']
    ordering = ['code']
    autocomplete_fields = ['city']

    @admin.display(description='District')
    def get_district(self, obj):
        return obj.city.district.name

    @admin.display(description='State')
    def get_state(self, obj):
        return obj.city.district.state.name


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ['name', 'pincode', 'get_city']
    list_filter = ['pincode__city__district__state']
    search_fields = ['name', 'pincode__code', 'pincode__city__name']
    ordering = ['pincode__code', 'name']
    autocomplete_fields = ['pincode']

    @admin.display(description='City')
    def get_city(self, obj):
        return obj.pincode.city.name

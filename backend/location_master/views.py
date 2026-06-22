from rest_framework import viewsets, filters
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from .models import Country, State, District, City, Pincode, Area
from .serializers import (
    CountrySerializer, StateSerializer, DistrictSerializer,
    CitySerializer, PincodeSerializer, AreaSerializer,
)
from django_tenants.utils import schema_context


class LocationBaseViewSet(viewsets.ReadOnlyModelViewSet):
    """Base class: public read-only, search-enabled. Forces public schema."""
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        # ALWAYS use public schema for location master data, 
        # regardless of which tenant subdomain is being used.
        with schema_context('public'):
            return super().dispatch(request, *args, **kwargs)

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ['name']
    ordering = ['name']
    pagination_class = None  # return all results for autocomplete (filtered by search)


class CountryViewSet(LocationBaseViewSet):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    search_fields = ['name', 'code']
    filterset_fields = []


class StateViewSet(LocationBaseViewSet):
    queryset = State.objects.select_related('country').all()
    serializer_class = StateSerializer
    search_fields = ['name', 'code']
    filterset_fields = ['country']


class DistrictViewSet(LocationBaseViewSet):
    queryset = District.objects.select_related('state').all()
    serializer_class = DistrictSerializer
    search_fields = ['name']
    filterset_fields = ['state']


class CityViewSet(LocationBaseViewSet):
    queryset = City.objects.select_related('district__state').all()
    serializer_class = CitySerializer
    search_fields = ['name']
    filterset_fields = ['district']


class PincodeViewSet(LocationBaseViewSet):
    queryset = Pincode.objects.select_related('city').all()
    serializer_class = PincodeSerializer
    search_fields = ['code']
    filterset_fields = ['city']
    ordering = ['code']
    ordering_fields = ['code']


class AreaViewSet(LocationBaseViewSet):
    queryset = Area.objects.select_related('pincode__city').all()
    serializer_class = AreaSerializer
    search_fields = ['name']
    filterset_fields = ['pincode']

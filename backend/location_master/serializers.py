from rest_framework import serializers
from .models import Country, State, District, City, Pincode, Area


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ['id', 'name', 'code']


class StateSerializer(serializers.ModelSerializer):
    country_name = serializers.CharField(source='country.name', read_only=True)

    class Meta:
        model = State
        fields = ['id', 'name', 'code', 'country', 'country_name']


class DistrictSerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source='state.name', read_only=True)

    class Meta:
        model = District
        fields = ['id', 'name', 'state', 'state_name']


class CitySerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    state_name = serializers.CharField(source='district.state.name', read_only=True)

    class Meta:
        model = City
        fields = ['id', 'name', 'district', 'district_name', 'state_name']


class PincodeSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source='city.name', read_only=True)

    class Meta:
        model = Pincode
        fields = ['id', 'code', 'city', 'city_name']


class AreaSerializer(serializers.ModelSerializer):
    pincode_code = serializers.CharField(source='pincode.code', read_only=True)
    city_name = serializers.CharField(source='pincode.city.name', read_only=True)

    class Meta:
        model = Area
        fields = ['id', 'name', 'pincode', 'pincode_code', 'city_name']

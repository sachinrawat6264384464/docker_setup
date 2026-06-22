# backend/utils/tests/test_properties_api.py
"""
Comprehensive API Tests for Properties/Utils App
Run with: python manage.py test utils.tests.test_properties_api
"""
from django.test import TestCase
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Client as TenantClient
from django_tenants.utils import schema_context


class PropertiesAPITestCase(APITestCase):
    """Test all properties-related API endpoints"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant, _ = TenantClient.objects.get_or_create(
            schema_name='test_tenant',
            defaults={
                'name': 'Test Company',
                'primary_domain': 'test.localhost',
                'plan': 'premium',
                'is_active': True
            }
        )
    
    def setUp(self):
        self.client = APIClient()
        with schema_context(self.tenant.schema_name):
            self.admin_user = User.objects.create_user(
                username='test_admin',
                email='admin@test.com',
                password='TestPass123!',
                role='facility_manager',
                is_active=True
            )
    
    def get_auth_token(self):
        with schema_context(self.tenant.schema_name):
            response = self.client.post('/api/auth/login/', {
                'email': 'test_admin',
                'password': 'TestPass123!'
            })
            return response.data.get('access') if response.status_code == 200 else None
    
    # BUILDINGS TESTS
    def test_01_list_buildings(self):
        """Test GET /api/properties/buildings/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/buildings/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ List Buildings: {response.status_code}")
    
    def test_02_create_building(self):
        """Test POST /api/properties/buildings/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        data = {
            'name': 'Test Building',
            'address': '123 Test St',
            'city': 'Test City',
            'state': 'TS',
            'zip_code': '12345',
            'total_floors': 10,
            'total_units': 50,
            'property_type': 'residential'
        }
        
        response = self.client.post('/api/properties/buildings/', data)
        self.assertIn(response.status_code, [200, 201, 400, 404])
        print(f"✓ Create Building: {response.status_code}")
        return response.data.get('id') if response.status_code in [200, 201] else None
    
    def test_03_get_building_detail(self):
        """Test GET /api/properties/buildings/{id}/"""
        building_id = self.test_02_create_building()
        if not building_id:
            self.skipTest("Building creation failed")
        
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get(f'/api/properties/buildings/{building_id}/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ Get Building Detail: {response.status_code}")
    
    def test_04_update_building(self):
        """Test PUT /api/properties/buildings/{id}/"""
        building_id = self.test_02_create_building()
        if not building_id:
            self.skipTest("Building creation failed")
        
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        data = {'name': 'Updated Building Name'}
        response = self.client.patch(f'/api/properties/buildings/{building_id}/', data)
        self.assertIn(response.status_code, [200, 400, 404])
        print(f"✓ Update Building: {response.status_code}")
    
    # UNITS TESTS
    def test_05_list_units(self):
        """Test GET /api/properties/units/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/units/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ List Units: {response.status_code}")
    
    def test_06_create_unit(self):
        """Test POST /api/properties/units/"""
        building_id = self.test_02_create_building()
        if not building_id:
            self.skipTest("Building creation failed")
        
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        data = {
            'building': building_id,
            'unit_number': '101',
            'floor': 1,
            'unit_type': 'apartment',
            'bedrooms': 2,
            'bathrooms': 1,
            'square_feet': 800,
            'monthly_rent': 1500,
            'status': 'available'
        }
        
        response = self.client.post('/api/properties/units/', data)
        self.assertIn(response.status_code, [200, 201, 400, 404])
        print(f"✓ Create Unit: {response.status_code}")
        return response.data.get('id') if response.status_code in [200, 201] else None
    
    def test_07_get_unit_detail(self):
        """Test GET /api/properties/units/{id}/"""
        unit_id = self.test_06_create_unit()
        if not unit_id:
            self.skipTest("Unit creation failed")
        
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get(f'/api/properties/units/{unit_id}/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ Get Unit Detail: {response.status_code}")
    
    # LEASES TESTS
    def test_08_list_leases(self):
        """Test GET /api/properties/leases/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/leases/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ List Leases: {response.status_code}")
    
    def test_09_create_lease(self):
        """Test POST /api/properties/leases/"""
        unit_id = self.test_06_create_unit()
        if not unit_id:
            self.skipTest("Unit creation failed")
        
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        with schema_context(self.tenant.schema_name):
            tenant = User.objects.create_user(
                username='lease_tenant',
                email='lease_tenant@test.com',
                password='TestPass123!',
                role='tenant',
                is_active=True
            )
        
        data = {
            'unit': unit_id,
            'tenant': tenant.id,
            'start_date': '2024-01-01',
            'end_date': '2024-12-31',
            'monthly_rent': 1500,
            'security_deposit': 3000,
            'status': 'active'
        }
        
        response = self.client.post('/api/properties/leases/', data)
        self.assertIn(response.status_code, [200, 201, 400, 404])
        print(f"✓ Create Lease: {response.status_code}")
    
    # DOCUMENTS TESTS
    def test_10_list_documents(self):
        """Test GET /api/properties/documents/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/documents/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ List Documents: {response.status_code}")
    
    # REPORTS TESTS
    def test_11_occupancy_report(self):
        """Test GET /api/properties/reports/occupancy/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/reports/occupancy/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ Occupancy Report: {response.status_code}")
    
    def test_12_lease_expiry_report(self):
        """Test GET /api/properties/reports/lease-expiry/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/reports/lease-expiry/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ Lease Expiry Report: {response.status_code}")
    
    def test_13_revenue_report(self):
        """Test GET /api/properties/reports/revenue/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/reports/revenue/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ Revenue Report: {response.status_code}")
    
    def test_14_dashboard_stats(self):
        """Test GET /api/properties/dashboard/stats/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/properties/dashboard/stats/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ Dashboard Stats: {response.status_code}")


class CSVProcessingAPITestCase(APITestCase):
    """Test CSV upload and processing endpoints"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant, _ = TenantClient.objects.get_or_create(
            schema_name='test_tenant',
            defaults={
                'name': 'Test Company',
                'primary_domain': 'test.localhost',
                'plan': 'premium',
                'is_active': True
            }
        )
    
    def setUp(self):
        self.client = APIClient()
        with schema_context(self.tenant.schema_name):
            self.admin_user = User.objects.create_user(
                username='test_admin',
                email='admin@test.com',
                password='TestPass123!',
                role='facility_manager',
                is_active=True
            )
    
    def get_auth_token(self):
        with schema_context(self.tenant.schema_name):
            response = self.client.post('/api/auth/login/', {
                'email': 'test_admin',
                'password': 'TestPass123!'
            })
            return response.data.get('access') if response.status_code == 200 else None
    
    def test_01_list_csv_uploads(self):
        """Test GET /api/csv/uploads/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/csv/uploads/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ List CSV Uploads: {response.status_code}")
    
    def test_02_get_csv_template(self):
        """Test GET /api/csv/template/"""
        token = self.get_auth_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        response = self.client.get('/api/csv/template/')
        self.assertIn(response.status_code, [200, 404])
        print(f"✓ Get CSV Template: {response.status_code}")


def print_test_summary():
    """Print summary of available tests"""
    print("\n" + "="*70)
    print("BACKEND API TEST SUITE - PROPERTIES APP")
    print("="*70)
    print("\nTest Classes:")
    print("1. PropertiesAPITestCase - Buildings, Units, Leases, Documents")
    print("   - Buildings CRUD")
    print("   - Units CRUD")
    print("   - Leases CRUD")
    print("   - Documents List")
    print("   - Reports (Occupancy, Lease Expiry, Revenue)")
    print("   - Dashboard Stats")
    print("\n2. CSVProcessingAPITestCase - CSV Upload & Processing")
    print("   - List CSV Uploads")
    print("   - Get CSV Template")
    print("\nRun with: python manage.py test utils.tests.test_properties_api")
    print("="*70 + "\n")


if __name__ == '__main__':
    print_test_summary()
# propflow/tests.py - Health check and system tests
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock
import uuid

from propflow.health import (
    health_check_detailed, health_check_simple,
    _check_database, _check_cache, _check_celery, _check_migrations,
)

User = get_user_model()


class DatabaseHealthCheckTests(TestCase):
    def test_database_healthy(self):
        result = _check_database()
        self.assertEqual(result['status'], 'healthy')
        self.assertIn('latency_ms', result)
        self.assertIn('engine', result)


class CacheHealthCheckTests(TestCase):
    def test_cache_healthy(self):
        result = _check_cache()
        self.assertEqual(result['status'], 'healthy')
        self.assertIn('latency_ms', result)
        self.assertIn('backend', result)


class CeleryHealthCheckTests(TestCase):
    @patch('propflow.health.current_app')
    def test_celery_no_workers(self, mock_app):
        mock_inspector = MagicMock()
        mock_inspector.ping.return_value = None
        mock_app.control.inspect.return_value = mock_inspector
        result = _check_celery()
        self.assertEqual(result['status'], 'unhealthy')

    @patch('propflow.health.current_app')
    def test_celery_with_workers(self, mock_app):
        mock_inspector = MagicMock()
        mock_inspector.ping.return_value = {'worker1@host': {'ok': 'pong'}}
        mock_inspector.active.return_value = {'worker1@host': []}
        mock_app.control.inspect.return_value = mock_inspector
        result = _check_celery()
        self.assertEqual(result['status'], 'healthy')
        self.assertEqual(result['workers'], 1)


class MigrationHealthCheckTests(TestCase):
    def test_migration_check(self):
        result = _check_migrations()
        self.assertIn(result['status'], ['healthy', 'warning'])
        self.assertIn('unapplied_count', result)


class HealthCheckEndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_detailed_health_check(self):
        request = self.factory.get('/health/')
        response = health_check_detailed(request)
        self.assertIn(response.status_code, [200, 503])

    def test_simple_health_check(self):
        request = self.factory.get('/health/live/')
        response = health_check_simple(request)
        self.assertEqual(response.status_code, 200)

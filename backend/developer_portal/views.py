from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from .models import APIKey, WebhookEndpoint, WebhookDelivery, APIGuide, APIChangelog
from .serializers import (APIKeySerializer, WebhookEndpointSerializer,
                           WebhookDeliverySerializer, APIGuideSerializer,
                           APIChangelogSerializer)
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema


class APIKeyListView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = APIKeySerializer

    @extend_schema(responses=APIKeySerializer(many=True))
    def get(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        keys = APIKey.objects.filter(tenant_schema=schema, is_active=True)
        return Response(APIKeySerializer(keys, many=True).data)


class APIKeyCreateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = APIKeySerializer

    @extend_schema(request=OpenApiTypes.OBJECT, responses=APIKeySerializer)
    def post(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        name = request.data.get('name', 'API Key')
        scopes = request.data.get('scopes', [])
        obj, raw_key = APIKey.generate(
            tenant_schema=schema,
            name=name,
            created_by=request.user,
            scopes=scopes,
        )
        data = APIKeySerializer(obj).data
        data['key'] = raw_key  # shown once only
        return Response(data, status=201)


class APIKeyRevokeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = APIKeySerializer

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        key = get_object_or_404(APIKey, pk=pk, tenant_schema=schema)
        key.is_active = False
        key.save()
        return Response({'message': 'API key revoked'})


class WebhookEndpointView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WebhookEndpointSerializer

    @extend_schema(responses=WebhookEndpointSerializer(many=True))
    def get(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        endpoints = WebhookEndpoint.objects.filter(tenant_schema=schema)
        return Response(WebhookEndpointSerializer(endpoints, many=True).data)

    @extend_schema(request=WebhookEndpointSerializer, responses=WebhookEndpointSerializer)
    def post(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        serializer = WebhookEndpointSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(tenant_schema=schema)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class WebhookDeliveryView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WebhookDeliverySerializer

    @extend_schema(responses=WebhookDeliverySerializer(many=True))
    def get(self, request, pk):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        endpoint = get_object_or_404(WebhookEndpoint, pk=pk, tenant_schema=schema)
        deliveries = endpoint.deliveries.order_by('-created_at')[:50]
        return Response(WebhookDeliverySerializer(deliveries, many=True).data)


class APIGuideListView(APIView):
    permission_classes = [AllowAny]
    serializer_class = APIGuideSerializer

    @extend_schema(responses=APIGuideSerializer(many=True))
    def get(self, request):
        guides = APIGuide.objects.filter(is_published=True)
        return Response(APIGuideSerializer(guides, many=True).data)


class APIGuideDetailView(APIView):
    permission_classes = [AllowAny]
    serializer_class = APIGuideSerializer

    @extend_schema(responses=APIGuideSerializer)
    def get(self, request, slug):
        guide = get_object_or_404(APIGuide, slug=slug, is_published=True)
        return Response(APIGuideSerializer(guide).data)


class APIChangelogView(APIView):
    permission_classes = [AllowAny]
    serializer_class = APIChangelogSerializer

    @extend_schema(responses=APIChangelogSerializer(many=True))
    def get(self, request):
        entries = APIChangelog.objects.filter(is_published=True)
        return Response(APIChangelogSerializer(entries, many=True).data)

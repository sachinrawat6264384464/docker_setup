from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from .models import SiteContent, Testimonial, ContactLead, FAQItem
from .serializers import (SiteContentSerializer, TestimonialSerializer,
                          ContactLeadSerializer, ContactLeadAdminSerializer, FAQItemSerializer)

SITE_CONFIG_KEY = 'site_config'


class SiteConfigView(APIView):
    """
    GET  /api/website/config/        — public, returns full site config JSON
    PUT  /api/website/admin/config/  — admin only, saves full site config JSON
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request):
        try:
            obj = SiteContent.objects.get(key=SITE_CONFIG_KEY)
            return Response(obj.value)
        except SiteContent.DoesNotExist:
            return Response({})

    def put(self, request):
        obj, _ = SiteContent.objects.update_or_create(
            key=SITE_CONFIG_KEY,
            defaults={'value': request.data, 'section': 'global'},
        )
        return Response(obj.value)


class SiteContentView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        section = request.query_params.get('section')
        qs = SiteContent.objects.all()
        if section:
            qs = qs.filter(section=section)
        data = {item.key: item.value for item in qs}
        return Response(data)


# =============================================================================
# TESTIMONIALS  (public read, admin CRUD)
# =============================================================================

class TestimonialListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        items = Testimonial.objects.filter(is_active=True)
        return Response(TestimonialSerializer(items, many=True).data)


class AdminTestimonialListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = Testimonial.objects.all()
        return Response(TestimonialSerializer(items, many=True).data)

    def post(self, request):
        serializer = TestimonialSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminTestimonialDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        return get_object_or_404(Testimonial, pk=pk)

    def put(self, request, pk):
        obj = self.get_object(pk)
        serializer = TestimonialSerializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# FAQ ITEMS  (public read, admin CRUD)
# =============================================================================

class FAQListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        items = FAQItem.objects.filter(is_active=True)
        return Response(FAQItemSerializer(items, many=True).data)


class AdminFAQListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = FAQItem.objects.all()
        return Response(FAQItemSerializer(items, many=True).data)

    def post(self, request):
        serializer = FAQItemSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminFAQDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        return get_object_or_404(FAQItem, pk=pk)

    def put(self, request, pk):
        obj = self.get_object(pk)
        serializer = FAQItemSerializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# CONTACT LEADS
# =============================================================================

class ContactLeadCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ContactLeadSerializer(data=request.data)
        if serializer.is_valid():
            lead = serializer.save()
            try:
                owner_email = getattr(settings, 'PLATFORM_OWNER_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None)
                if owner_email:
                    send_mail(
                        subject=f'[HOAConnectHub] New Contact from {lead.name}',
                        message=(
                            f'New contact form submission:\n\n'
                            f'Name:    {lead.name or "—"}\n'
                            f'Email:   {lead.email or "—"}\n'
                            f'Company: {lead.company or "—"}\n'
                            f'Phone:   {lead.phone or "—"}\n\n'
                            f'Message:\n{lead.message or "—"}\n\n'
                            f'Review at /admin/contact-submissions'
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[owner_email],
                        fail_silently=True,
                    )
            except Exception:
                pass
            return Response({'message': 'Thank you! We will be in touch shortly.'}, status=201)
        return Response(serializer.errors, status=400)


class AdminLeadsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        leads = ContactLead.objects.all()
        return Response(ContactLeadAdminSerializer(leads, many=True).data)


class AdminLeadDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        lead = get_object_or_404(ContactLead, pk=pk)
        lead.status = request.data.get('status', lead.status)
        lead.save(update_fields=['status'])
        return Response(ContactLeadAdminSerializer(lead).data)


class AdminSiteContentUpdateView(APIView):
    """Legacy key-by-key content updater. Kept for backward compat."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        section = request.data.get('_section', '')
        # Pre-validate fields
        for key, value in request.data.items():
            if key == '_section':
                continue
            
            if key == 'platform_name':
                if not value or not str(value).strip():
                    return Response({"error": "Platform Name cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
                import re
                if not re.match(r'^[a-zA-Z0-9\s._-]+$', str(value)):
                    return Response({"error": "Platform Name can only contain letters, numbers, spaces, dots, underscores, and hyphens."}, status=status.HTTP_400_BAD_REQUEST)
            
            if key in ('support_email', 'from_email'):
                if not value or not str(value).strip():
                    return Response({"error": f"{key.replace('_', ' ').capitalize()} cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
                from django.core.validators import validate_email
                from django.core.exceptions import ValidationError
                try:
                    validate_email(str(value).strip())
                except ValidationError:
                    return Response({"error": f"Invalid {key.replace('_', ' ').capitalize()} format."}, status=status.HTTP_400_BAD_REQUEST)
            
            if key == 'max_tenants':
                try:
                    val = int(value)
                    if val <= 0:
                        return Response({"error": "Max tenants must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)
                except (ValueError, TypeError):
                    return Response({"error": "Max tenants must be a valid integer."}, status=status.HTTP_400_BAD_REQUEST)

            if key in ('session_timeout_minutes', 'max_login_attempts', 'password_min_length'):
                try:
                    val = int(value)
                    if val < 0:
                        return Response({"error": f"{key.replace('_', ' ').capitalize()} cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
                except (ValueError, TypeError):
                    pass

        # If all valid, perform update/create
        for key, value in request.data.items():
            if key == '_section':
                continue
            SiteContent.objects.update_or_create(
                key=key, defaults={'value': value, 'section': section}
            )
        return Response({'message': 'Content updated'})

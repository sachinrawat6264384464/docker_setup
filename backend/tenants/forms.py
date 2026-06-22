# tenants/forms.py - Custom Forms for Tenant Admin
from django import forms
from django.core.exceptions import ValidationError
from .models import Client, Domain
import re


class ClientAdminForm(forms.ModelForm):
    """
    Custom form for Client admin with auto-populated features
    """
    # Add a domain field for convenience
    primary_domain = forms.CharField(
        max_length=253,
        required=False,
        help_text="Primary domain for this tenant (e.g., abc.localhost:8000)",
        label="Primary Domain"
    )
    
    class Meta:
        model = Client
        fields = '__all__'
        exclude = []  # Don't exclude schema_name, we'll handle it
        widgets = {
            'features': forms.Textarea(attrs={
                'rows': 15, 
                'cols': 80,
                'placeholder': 'Features will be auto-populated based on subscription plan'
            }),
            'description': forms.Textarea(attrs={'rows': 4}),
            'address': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Make schema_name not required for new tenants
        if not self.instance.pk:
            if 'schema_name' in self.fields:
                self.fields['schema_name'].required = False
                self.fields['schema_name'].widget = forms.HiddenInput()
        
        # Auto-populate features if creating new tenant
        if not self.instance.pk:
            # Set default features based on subscription plan
            plan = self.initial.get('subscription_plan', 'basic')
            self.initial['features'] = self.get_default_features(plan)
            
        # Make schema_name readonly if editing existing tenant
        if self.instance.pk:
            self.fields['schema_name'].disabled = True
            
            # Load existing primary domain if available
            primary_domain = self.instance.domains.filter(is_primary=True).first()
            if primary_domain:
                self.initial['primary_domain'] = primary_domain.domain
    
    def get_default_features(self, plan):
        """Get default features based on subscription plan"""
        # Basic features for all plans
        basic_features = {
            'people_hub': True,
            'csv_upload': True,
            'properties': True,
            'maintenance': True,
            'payments': True,
            'notifications': True,
        }
        
        # Premium features
        premium_features = {
            'amenities': True,
            'visitor_management': True,
            'advanced_reports': True,
        }
        
        # Enterprise features
        enterprise_features = {
            'marketplace': True,
            'analytics': True,
            'custom_integrations': True,
            'api_access': True,
            'white_labeling': True,
        }
        
        if plan == 'basic':
            return {**basic_features, **{k: False for k in {**premium_features, **enterprise_features}}}
        elif plan == 'premium':
            return {**basic_features, **premium_features, **{k: False for k in enterprise_features}}
        elif plan == 'enterprise':
            return {**basic_features, **premium_features, **enterprise_features}
        else:
            return basic_features
    
    def clean_primary_domain(self):
        """Validate domain format"""
        domain = self.cleaned_data.get('primary_domain')
        
        if not domain:
            return domain
        
        # Basic domain validation
        domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        
        # Allow localhost with port for development
        if 'localhost' in domain:
            if not re.match(r'^[a-zA-Z0-9\-]+\.localhost(:\d+)?$', domain):
                raise ValidationError(
                    "Invalid localhost domain format. Use: subdomain.localhost:8000"
                )
        elif not re.match(domain_pattern, domain):
            raise ValidationError("Invalid domain format")
        
        # Check if domain already exists (for new tenants or domain changes)
        existing_domain = Domain.objects.filter(domain=domain)
        if self.instance.pk:
            # Exclude current tenant's domains
            existing_domain = existing_domain.exclude(tenant=self.instance)
        
        if existing_domain.exists():
            raise ValidationError(f"Domain '{domain}' is already in use by another tenant")
        
        return domain
    
    def clean_features(self):
        """Ensure features is a valid dictionary"""
        features = self.cleaned_data.get('features')
        
        if not features:
            # Use default features based on subscription plan
            plan = self.cleaned_data.get('subscription_plan', 'basic')
            features = self.get_default_features(plan)
        
        if not isinstance(features, dict):
            raise ValidationError("Features must be a dictionary")
        
        return features
    
    def clean_schema_name(self):
        """Clean and generate schema_name"""
        schema_name = self.cleaned_data.get('schema_name')
        
        # If creating new tenant and no schema_name provided, generate it
        if not self.instance.pk and not schema_name:
            # Get name from cleaned_data first, if not available try from raw data
            name = self.cleaned_data.get('name') or self.data.get('name', '')
            
            if not name:
                # Return a temporary value, will be set properly in save()
                return 'temp_schema'
            
            # Create safe schema name
            safe_name = name.lower().replace(' ', '_').replace('-', '_')
            safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
            
            # Ensure it starts with a letter (PostgreSQL requirement)
            if not safe_name or not safe_name[0].isalpha():
                safe_name = 'tenant_' + safe_name
            else:
                safe_name = 'tenant_' + safe_name
            
            # Ensure uniqueness
            counter = 1
            original_schema = safe_name
            while Client.objects.filter(schema_name=safe_name).exists():
                safe_name = f"{original_schema}_{counter}"
                counter += 1
            
            schema_name = safe_name
        
        # Ensure schema_name is never None or empty
        if not schema_name:
            schema_name = 'tenant_default'
        
        return schema_name
    
    def clean(self):
        """Additional validation"""
        cleaned_data = super().clean()
        
        # Ensure name is provided
        if not cleaned_data.get('name'):
            raise ValidationError("Company name is required")
        
        return cleaned_data
    
    def save(self, commit=True):
        """Save tenant and create domain if provided"""
        instance = super().save(commit=False)
        
        # Ensure schema_name is properly set
        if not instance.schema_name or instance.schema_name == 'temp_schema':
            name = instance.name
            safe_name = name.lower().replace(' ', '_').replace('-', '_')
            safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
            schema_name = f"tenant_{safe_name}"
            
            # Ensure uniqueness
            counter = 1
            original_schema = schema_name
            while Client.objects.filter(schema_name=schema_name).exists():
                schema_name = f"{original_schema}_{counter}"
                counter += 1
            
            instance.schema_name = schema_name
        
        # Ensure features are set
        if not instance.features:
            instance.features = self.get_default_features(instance.subscription_plan)
        
        if commit:
            instance.save()
            
            # Create or update primary domain
            primary_domain = self.cleaned_data.get('primary_domain')
            if primary_domain:
                # Check if tenant has existing primary domain
                existing_primary = instance.domains.filter(is_primary=True).first()
                
                if existing_primary:
                    if existing_primary.domain != primary_domain:
                        # Update existing primary domain
                        existing_primary.domain = primary_domain
                        existing_primary.save()
                else:
                    # Create new primary domain
                    Domain.objects.create(
                        tenant=instance,
                        domain=primary_domain,
                        is_primary=True
                    )
        
        return instance


class DomainAdminForm(forms.ModelForm):
    """
    Custom form for Domain admin with validation
    """
    class Meta:
        model = Domain
        fields = '__all__'
    
    def clean_domain(self):
        """Validate domain format and uniqueness"""
        domain = self.cleaned_data.get('domain')
        
        # Basic domain validation
        domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        
        # Allow localhost with port for development
        if 'localhost' in domain:
            if not re.match(r'^[a-zA-Z0-9\-]+\.localhost(:\d+)?$', domain):
                raise ValidationError(
                    "Invalid localhost domain format. Use: subdomain.localhost:8000"
                )
        elif not re.match(domain_pattern, domain):
            raise ValidationError("Invalid domain format")
        
        # Check uniqueness
        existing = Domain.objects.filter(domain=domain)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        
        if existing.exists():
            raise ValidationError(f"Domain '{domain}' already exists")
        
        return domain
    
    def clean(self):
        """Validate primary domain logic"""
        cleaned_data = super().clean()
        is_primary = cleaned_data.get('is_primary', False)
        tenant = cleaned_data.get('tenant')
        
        if is_primary and tenant:
            # Check if tenant already has a primary domain
            existing_primary = Domain.objects.filter(
                tenant=tenant, 
                is_primary=True
            )
            
            if self.instance.pk:
                existing_primary = existing_primary.exclude(pk=self.instance.pk)
            
            if existing_primary.exists():
                raise ValidationError(
                    f"Tenant '{tenant.name}' already has a primary domain: {existing_primary.first().domain}. "
                    "Please set that domain's 'is_primary' to False first, or set this domain as non-primary."
                )
        
        return cleaned_data
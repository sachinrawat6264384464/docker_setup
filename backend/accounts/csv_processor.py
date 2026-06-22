# accounts/csv_processor.py - Complete CSV Processing Engine
import pandas as pd
import uuid
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction
from io import StringIO, BytesIO
from .csv_models import CSVUpload, CSVRowResult, CSVTemplate

logger = logging.getLogger(__name__)

class CSVProcessingEngine:
    """
    Complete CSV processing engine for resident data import
    """
    
    # Standard column mappings and validations
    RESIDENT_REQUIRED_COLUMNS = [
        'first_name', 'last_name', 'email', 'phone', 
        'unit_number', 'building_name'
    ]
    
    RESIDENT_OPTIONAL_COLUMNS = [
        'emergency_contact_name', 'emergency_contact_phone',
        'lease_start_date', 'lease_end_date', 'monthly_rent',
        'security_deposit', 'date_of_birth', 'occupation',
        'unit_type', 'floor', 'area_sqft', 'bedrooms', 'bathrooms'
    ]
    
    def __init__(self, csv_upload: CSVUpload):
        self.csv_upload = csv_upload
        self.tenant_id = csv_upload.uploaded_by.tenant_id
        self.errors = []
        self.warnings = []
        self.processed_count = 0
        self.success_count = 0
        self.error_count = 0
        self.warning_count = 0
        self.processing_results = []
        
        # Get User model to avoid circular imports
        self.User = get_user_model()
        
    def process_file(self) -> Dict[str, Any]:
        """
        Main entry point for processing CSV file
        """
        try:
            self.csv_upload.status = 'processing'
            self.csv_upload.processing_started_at = timezone.now()
            self.csv_upload.save()
            
            # Read and validate CSV structure
            df = self._read_csv_file()
            if df is None:
                return self._complete_processing_with_error("Failed to read CSV file")
            
            # Validate CSV structure
            validation_result = self._validate_csv_structure(df)
            if not validation_result['valid']:
                return self._complete_processing_with_error(validation_result['error'])
            
            # Process each row
            self._process_rows(df)
            
            # Complete processing
            return self._complete_processing()
            
        except Exception as e:
            logger.error(f"CSV processing failed: {str(e)}")
            return self._complete_processing_with_error(f"Processing failed: {str(e)}")
    
    def _read_csv_file(self) -> pd.DataFrame:
        """Read CSV file and return DataFrame"""
        try:
            # Try different encodings
            encodings = ['utf-8', 'latin-1', 'cp1252']
            
            for encoding in encodings:
                try:
                    # Reset file pointer
                    self.csv_upload.file.seek(0)
                    
                    if self.csv_upload.file.name.endswith('.csv'):
                        df = pd.read_csv(
                            self.csv_upload.file,
                            encoding=encoding,
                            na_values=['', 'NULL', 'null', 'None', 'N/A', 'n/a'],
                            keep_default_na=True
                        )
                    else:
                        # Try Excel files
                        df = pd.read_excel(self.csv_upload.file)
                    
                    # Clean column names
                    df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
                    df.columns = df.columns.str.replace('[^a-zA-Z0-9_]', '', regex=True)
                    
                    logger.info(f"Successfully read CSV with {len(df)} rows using {encoding} encoding")
                    return df
                    
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.warning(f"Failed to read with {encoding}: {str(e)}")
                    continue
            
            raise ValueError("Could not read file with any supported encoding")
            
        except Exception as e:
            logger.error(f"Error reading CSV file: {str(e)}")
            self.errors.append(f"File reading error: {str(e)}")
            return None
    
    def _validate_csv_structure(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate CSV structure and columns"""
        if df.empty:
            return {'valid': False, 'error': 'CSV file is empty'}
        
        # Check for required columns
        missing_columns = []
        for col in self.RESIDENT_REQUIRED_COLUMNS:
            if col not in df.columns:
                missing_columns.append(col)
        
        if missing_columns:
            return {
                'valid': False, 
                'error': f"Missing required columns: {', '.join(missing_columns)}"
            }
        
        # Check for completely empty required columns
        empty_columns = []
        for col in self.RESIDENT_REQUIRED_COLUMNS:
            if df[col].isna().all():
                empty_columns.append(col)
        
        if empty_columns:
            return {
                'valid': False,
                'error': f"Required columns are completely empty: {', '.join(empty_columns)}"
            }
        
        # Update upload record with total rows
        self.csv_upload.total_rows = len(df)
        self.csv_upload.save()
        
        return {'valid': True}
    
    def _process_rows(self, df: pd.DataFrame):
        """Process each row of the CSV"""
        for index, row in df.iterrows():
            row_number = index + 2  # +2 because CSV rows start at 2 (1 is header)
            
            try:
                result = self._process_single_row(row, row_number)
                self._save_row_result(row, row_number, result)
                
                if result['status'] == 'success':
                    self.success_count += 1
                elif result['status'] == 'error':
                    self.error_count += 1
                elif result['status'] == 'warning':
                    self.warning_count += 1
                
                self.processed_count += 1
                
                # Update progress every 10 rows
                if self.processed_count % 10 == 0:
                    self.csv_upload.processed_rows = self.processed_count
                    self.csv_upload.save()
                
            except Exception as e:
                logger.error(f"Error processing row {row_number}: {str(e)}")
                self._save_row_result(row, row_number, {
                    'status': 'error',
                    'message': f"Unexpected error: {str(e)}",
                    'details': {}
                })
                self.error_count += 1
                self.processed_count += 1
    
    def _process_single_row(self, row: pd.Series, row_number: int) -> Dict[str, Any]:
        """Process a single CSV row"""
        try:
            # Clean and validate data
            cleaned_data = self._clean_row_data(row)
            
            # Validate required fields
            validation_result = self._validate_row_data(cleaned_data, row_number)
            if not validation_result['valid']:
                return {
                    'status': 'error',
                    'message': validation_result['error'],
                    'details': validation_result.get('details', {})
                }
            
            # Check for existing user
            existing_check = self._check_existing_user(cleaned_data)
            if existing_check['exists']:
                return {
                    'status': 'warning',
                    'message': existing_check['message'],
                    'details': {'existing_user_id': existing_check['user_id']}
                }
            
            # Create user and related objects
            with transaction.atomic():
                result = self._create_user_and_related_objects(cleaned_data)
                return result
                
        except Exception as e:
            logger.error(f"Error processing row {row_number}: {str(e)}")
            return {
                'status': 'error',
                'message': f"Processing error: {str(e)}",
                'details': {}
            }
    
    def _clean_row_data(self, row: pd.Series) -> Dict[str, Any]:
        """Clean and normalize row data"""
        cleaned = {}
        
        # Basic string fields
        string_fields = ['first_name', 'last_name', 'unit_number', 'building_name', 
                        'emergency_contact_name', 'occupation', 'unit_type']
        
        for field in string_fields:
            if field in row and pd.notna(row[field]):
                cleaned[field] = str(row[field]).strip()
        
        # Email cleaning
        if 'email' in row and pd.notna(row['email']):
            cleaned['email'] = str(row['email']).strip().lower()
        
        # Phone number cleaning
        for phone_field in ['phone', 'emergency_contact_phone']:
            if phone_field in row and pd.notna(row[phone_field]):
                cleaned[phone_field] = self._clean_phone_number(str(row[phone_field]))
        
        # Numeric fields
        numeric_fields = ['monthly_rent', 'security_deposit', 'floor', 'area_sqft', 
                         'bedrooms', 'bathrooms']
        
        for field in numeric_fields:
            if field in row and pd.notna(row[field]):
                try:
                    cleaned[field] = float(row[field])
                except (ValueError, TypeError):
                    pass  # Will be caught in validation
        
        # Date fields
        date_fields = ['lease_start_date', 'lease_end_date', 'date_of_birth']
        for field in date_fields:
            if field in row and pd.notna(row[field]):
                cleaned[field] = self._parse_date(row[field])
        
        return cleaned
    
    def _clean_phone_number(self, phone: str) -> str:
        """Clean phone number"""
        if not phone:
            return ""
        
        # Remove all non-digits
        digits_only = re.sub(r'[^\d]', '', str(phone))
        
        # Basic validation - must be at least 10 digits
        if len(digits_only) < 10:
            return ""
        
        # Take last 10 digits if more than 10
        if len(digits_only) > 10:
            digits_only = digits_only[-10:]
        
        return digits_only
    
    def _parse_date(self, date_value) -> datetime.date:
        """Parse date from various formats"""
        if pd.isna(date_value):
            return None
        
        if isinstance(date_value, datetime):
            return date_value.date()
        
        if isinstance(date_value, str):
            # Try common date formats
            formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y']
            for fmt in formats:
                try:
                    return datetime.strptime(date_value.strip(), fmt).date()
                except ValueError:
                    continue
        
        return None
    
    def _validate_row_data(self, data: Dict[str, Any], row_number: int) -> Dict[str, Any]:
        """Validate cleaned row data"""
        errors = []
        
        # Required fields validation
        for field in self.RESIDENT_REQUIRED_COLUMNS:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")
        
        # Email validation
        if 'email' in data and data['email']:
            if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', data['email']):
                errors.append(f"Invalid email format: {data['email']}")
        
        # Phone validation
        if 'phone' in data and data['phone']:
            if len(data['phone']) != 10:
                errors.append(f"Phone number must be 10 digits: {data['phone']}")
        
        # Date validations
        if 'lease_start_date' in data and 'lease_end_date' in data:
            if (data['lease_start_date'] and data['lease_end_date'] and 
                data['lease_start_date'] >= data['lease_end_date']):
                errors.append("Lease start date must be before end date")
        
        if errors:
            return {
                'valid': False,
                'error': f"Row {row_number}: {'; '.join(errors)}",
                'details': {'validation_errors': errors}
            }
        
        return {'valid': True}
    
    def _check_existing_user(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Check if user already exists"""
        if 'email' not in data:
            return {'exists': False}
        
        try:
            existing_user = self.User.objects.get(email=data['email'])
            return {
                'exists': True,
                'user_id': str(existing_user.id),
                'message': f"User with email {data['email']} already exists"
            }
        except self.User.DoesNotExist:
            return {'exists': False}
    
    def _create_user_and_related_objects(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create user and related objects (building, unit, lease)"""
        created_objects = {}
        
        # Create/get building
        building = self._get_or_create_building(data)
        if building:
            created_objects['building_id'] = str(building.id)
        
        # Create/get unit
        unit = self._get_or_create_unit(data, building)
        if unit:
            created_objects['unit_id'] = str(unit.id)
        
        # Create user
        user = self._create_user(data)
        created_objects['user_id'] = str(user.id)
        
        # Assign user to unit
        if unit and user:
            unit.current_tenant = user
            unit.status = 'occupied'
            unit.save()
        
        # Create lease if dates provided
        if ('lease_start_date' in data and data['lease_start_date'] and
            unit and user):
            lease = self._create_lease(data, unit, user)
            if lease:
                created_objects['lease_id'] = str(lease.id)
        
        return {
            'status': 'success',
            'message': f"Created user {user.username} successfully",
            'details': created_objects
        }
    
    def _get_or_create_building(self, data: Dict[str, Any]):
        """Get or create building"""
        if 'building_name' not in data:
            return None
        
        try:
            from properties.models import Building
            building, created = Building.objects.get_or_create(
                name=data['building_name'],
                defaults={
                    'address': f"Address for {data['building_name']}",
                    'total_floors': data.get('floor', 10),
                    'total_units': 100,  # Default, will be updated
                    'building_type': 'residential'
                }
            )
            return building
        except Exception as e:
            logger.error(f"Error creating building: {str(e)}")
            return None
    
    def _get_or_create_unit(self, data: Dict[str, Any], building):
        """Get or create unit"""
        if not building or 'unit_number' not in data:
            return None
        
        try:
            from properties.models import Unit
            
            # Calculate floor from unit number if not provided
            floor = data.get('floor', 1)
            if not floor and data['unit_number'].isdigit():
                floor = max(1, int(data['unit_number']) // 100)
            
            unit, created = Unit.objects.get_or_create(
                building=building,
                unit_number=data['unit_number'],
                defaults={
                    'floor': floor,
                    'unit_type': data.get('unit_type', '2bhk'),
                    'area_sqft': data.get('area_sqft', 1000),
                    'bedrooms': data.get('bedrooms', 2),
                    'bathrooms': data.get('bathrooms', 2),
                    'monthly_rent': data.get('monthly_rent', 25000),
                    'security_deposit': data.get('security_deposit', data.get('monthly_rent', 25000) * 2),
                    'status': 'available'
                }
            )
            return unit
        except Exception as e:
            logger.error(f"Error creating unit: {str(e)}")
            return None
    
    def _create_user(self, data: Dict[str, Any]):
        """Create user"""
        # Generate unique username
        base_username = f"{data['first_name'].lower()}.{data['last_name'].lower()}"
        username = base_username
        counter = 1
        
        while self.User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        user = self.User.objects.create_user(
            username=username,
            email=data['email'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            phone=data.get('phone', ''),
            role='tenant',
            unit_number=data.get('unit_number', ''),
            building_name=data.get('building_name', ''),
            emergency_contact_name=data.get('emergency_contact_name', ''),
            emergency_contact_phone=data.get('emergency_contact_phone', ''),
            tenant_id=self.tenant_id,
            is_approved=True,
            email_verified=False
        )
        
        # Create profile with additional data
        if hasattr(user, 'profile'):
            profile = user.profile
        else:
            from accounts.models import UserProfile
            profile = UserProfile.objects.create(user=user)
        
        # Update profile with additional data
        if 'date_of_birth' in data and data['date_of_birth']:
            profile.date_of_birth = data['date_of_birth']
        
        if 'occupation' in data and data['occupation']:
            profile.occupation = data['occupation']
        
        profile.save()
        
        return user
    
    def _create_lease(self, data: Dict[str, Any], unit, user):
        """Create lease"""
        try:
            from properties.models import Lease
            
            end_date = data.get('lease_end_date')
            if not end_date:
                # Default to 1 year lease
                end_date = data['lease_start_date'] + timedelta(days=365)
            
            lease = Lease.objects.create(
                unit=unit,
                tenant=user,
                start_date=data['lease_start_date'],
                end_date=end_date,
                monthly_rent=data.get('monthly_rent', unit.monthly_rent),
                security_deposit=data.get('security_deposit', unit.security_deposit),
                status='active'
            )
            return lease
        except Exception as e:
            logger.error(f"Error creating lease: {str(e)}")
            return None
    
    def _save_row_result(self, row: pd.Series, row_number: int, result: Dict[str, Any]):
        """Save individual row processing result"""
        CSVRowResult.objects.create(
            csv_upload=self.csv_upload,
            row_number=row_number,
            result_type=result['status'],
            raw_data=row.to_dict(),
            message=result['message'],
            details=result.get('details', {}),
            created_user_id=result.get('details', {}).get('user_id'),
            created_building_id=result.get('details', {}).get('building_id'),
            created_unit_id=result.get('details', {}).get('unit_id')
        )
    
    def _complete_processing(self) -> Dict[str, Any]:
        """Complete processing and update upload record"""
        self.csv_upload.status = 'completed' if self.error_count == 0 else 'partial'
        self.csv_upload.processing_completed_at = timezone.now()
        self.csv_upload.processed_rows = self.processed_count
        self.csv_upload.success_count = self.success_count
        self.csv_upload.error_count = self.error_count
        self.csv_upload.warning_count = self.warning_count
        
        # Calculate processing time
        if self.csv_upload.processing_started_at:
            time_diff = self.csv_upload.processing_completed_at - self.csv_upload.processing_started_at
            self.csv_upload.processing_time_seconds = time_diff.total_seconds()
        
        # Create summary
        self.csv_upload.summary = {
            'total_rows': self.csv_upload.total_rows,
            'processed_rows': self.processed_count,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'warning_count': self.warning_count,
            'success_rate': self.csv_upload.success_rate,
            'processing_time_seconds': self.csv_upload.processing_time_seconds,
        }
        
        self.csv_upload.save()
        
        from .tasks import send_csv_completion_email_async
        send_csv_completion_email_async.delay(
            str(self.csv_upload.uploaded_by.id),
            str(self.csv_upload.id)
        )
        
        return {
            'success': True,
            'upload_id': str(self.csv_upload.id),
            'summary': self.csv_upload.summary,
            'message': f'Processing completed: {self.success_count} successful, {self.error_count} errors, {self.warning_count} warnings'
        }
    
    def _complete_processing_with_error(self, error_message: str) -> Dict[str, Any]:
        """Complete processing with error"""
        self.csv_upload.status = 'failed'
        self.csv_upload.processing_completed_at = timezone.now()
        self.csv_upload.errors = [error_message]
        
        if self.csv_upload.processing_started_at:
            time_diff = self.csv_upload.processing_completed_at - self.csv_upload.processing_started_at
            self.csv_upload.processing_time_seconds = time_diff.total_seconds()
        
        self.csv_upload.save()
        
        return {
            'success': False,
            'upload_id': str(self.csv_upload.id),
            'error': error_message
        }
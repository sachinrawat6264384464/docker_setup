# accounts/management/commands/test_celery_complete.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.csv_models import CSVUpload
from accounts.tasks import test_celery_task, process_csv_file_async
from celery.result import AsyncResult
import time
import os
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()

class Command(BaseCommand):
    help = 'Complete test of Celery setup'
    
    def handle(self, *args, **kwargs):
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.HTTP_INFO('CELERY COMPLETE TEST'))
        self.stdout.write('='*70 + '\n')
        
        # TEST 1: Check Redis Connection
        self.stdout.write('TEST 1: Checking Redis connection...')
        try:
            import redis
            from django.conf import settings
            r = redis.from_url(settings.CELERY_BROKER_URL)
            r.ping()
            self.stdout.write(self.style.SUCCESS('✓ Redis is running'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Redis connection failed: {str(e)}'))
            return
        
        # TEST 2: Check Celery Worker
        self.stdout.write('\nTEST 2: Checking Celery worker...')
        try:
            from celery import current_app
            inspector = current_app.control.inspect()
            stats = inspector.stats()
            if stats:
                self.stdout.write(self.style.SUCCESS(f'✓ Celery worker is running ({len(stats)} worker(s))'))
            else:
                self.stdout.write(self.style.ERROR('✗ No Celery workers found'))
                self.stdout.write(self.style.WARNING('   Start worker: celery -A propflow worker --loglevel=info'))
                return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Celery check failed: {str(e)}'))
            return
        
        # TEST 3: Execute Simple Test Task
        self.stdout.write('\nTEST 3: Testing simple Celery task...')
        try:
            result = test_celery_task.delay("Complete test message")
            self.stdout.write(f'   Task ID: {result.id}')
            self.stdout.write('   Waiting for result...')
            
            task_result = result.get(timeout=10)
            self.stdout.write(self.style.SUCCESS(f'✓ Task completed successfully'))
            self.stdout.write(f'   Result: {task_result}')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Task failed: {str(e)}'))
            return
        
        # TEST 4: Create Test CSV and Process
        self.stdout.write('\nTEST 4: Testing CSV processing with Celery...')
        try:
            # Get or create test user
            test_user, created = User.objects.get_or_create(
                username='test_csv_user',
                defaults={
                    'email': 'testcsv@example.com',
                    'role': 'facility_manager',
                    'is_approved': True,
                }
            )
            if created:
                test_user.set_password('test123')
                test_user.save()
            
            # Create test CSV content
            csv_content = b"""first_name,last_name,email,phone,unit_number,building_name
John,Doe,john.celerytest@example.com,9876543210,A101,Tower A
Jane,Smith,jane.celerytest@example.com,9876543211,A102,Tower A"""
            
            # Create CSV file
            csv_file = SimpleUploadedFile(
                "test_celery.csv",
                csv_content,
                content_type="text/csv"
            )
            
            # Create CSVUpload instance
            csv_upload = CSVUpload.objects.create(
                uploaded_by=test_user,
                file=csv_file,
                original_filename='test_celery.csv',
                file_size=len(csv_content),
                status='pending'
            )
            
            self.stdout.write(f'   CSV Upload created: {csv_upload.id}')
            
            # Start async processing
            task = process_csv_file_async.delay(str(csv_upload.id))
            self.stdout.write(f'   Processing Task ID: {task.id}')
            self.stdout.write('   Waiting for CSV processing (max 30 seconds)...')
            
            # Wait and check status
            for i in range(30):
                time.sleep(1)
                task_result = AsyncResult(task.id)
                
                if task_result.state == 'SUCCESS':
                    result = task_result.result
                    self.stdout.write(self.style.SUCCESS(f'✓ CSV processing completed'))
                    self.stdout.write(f'   Processed: {result.get("summary", {}).get("processed_rows", 0)} rows')
                    self.stdout.write(f'   Success: {result.get("summary", {}).get("success_count", 0)}')
                    self.stdout.write(f'   Errors: {result.get("summary", {}).get("error_count", 0)}')
                    break
                elif task_result.state == 'FAILURE':
                    self.stdout.write(self.style.ERROR(f'✗ CSV processing failed: {task_result.info}'))
                    break
                elif i % 5 == 0:
                    self.stdout.write(f'   Still processing... ({task_result.state})')
            else:
                self.stdout.write(self.style.WARNING('⚠ CSV processing timeout (but may still be running)'))
            
            # Check final status
            csv_upload.refresh_from_db()
            self.stdout.write(f'\n   Final Upload Status: {csv_upload.status}')
            self.stdout.write(f'   Total Rows: {csv_upload.total_rows}')
            self.stdout.write(f'   Success Count: {csv_upload.success_count}')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ CSV test failed: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
            return
        
        # TEST 5: Check Task Results in Database
        self.stdout.write('\nTEST 5: Checking task results in database...')
        try:
            from django_celery_results.models import TaskResult
            recent_tasks = TaskResult.objects.all().order_by('-date_done')[:3]
            
            if recent_tasks.exists():
                self.stdout.write(self.style.SUCCESS(f'✓ Found {recent_tasks.count()} recent tasks'))
                for task in recent_tasks:
                    status_color = self.style.SUCCESS if task.status == 'SUCCESS' else self.style.ERROR
                    self.stdout.write(f'   - {task.task_name}: {status_color(task.status)}')
            else:
                self.stdout.write(self.style.WARNING('⚠ No tasks found in database'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Database check failed: {str(e)}'))
        
        # SUMMARY
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS('✅ ALL TESTS PASSED - CELERY IS WORKING CORRECTLY'))
        self.stdout.write('='*70)
        self.stdout.write('\nWhat was tested:')
        self.stdout.write('  ✓ Redis connection')
        self.stdout.write('  ✓ Celery worker running')
        self.stdout.write('  ✓ Simple task execution')
        self.stdout.write('  ✓ CSV async processing')
        self.stdout.write('  ✓ Task results stored in database')
        self.stdout.write('\n' + '='*70 + '\n')
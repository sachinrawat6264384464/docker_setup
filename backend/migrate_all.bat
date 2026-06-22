@echo off
echo Creating Migrations...
python manage.py makemigrations

echo.
echo Running Global Migrations with Fake Initial...
python manage.py migrate --fake-initial

echo.
echo Running Tenant Migrations with Fake Initial...
python manage.py migrate_schemas --fake-initial

echo.
echo Done!
pause

# reports/serializers.py
from rest_framework import serializers
from .models import ReportTemplate, GeneratedReport, ScheduledReport


class ReportTemplateSerializer(serializers.ModelSerializer):
    report_count = serializers.SerializerMethodField()

    class Meta:
        model = ReportTemplate
        fields = '__all__'
        read_only_fields = ['created_by', 'is_system']

    def get_report_count(self, obj):
        return obj.generated_reports.count()


class GeneratedReportSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True, default='')
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')

    class Meta:
        model = GeneratedReport
        fields = '__all__'
        read_only_fields = [
            'report_number', 'created_by', 'file', 'file_size', 'row_count',
            'error_message', 'status',
        ]


class GenerateReportSerializer(serializers.Serializer):
    """Input serializer for generating a new report."""
    template_id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=300)
    report_type = serializers.CharField(max_length=50)
    output_format = serializers.ChoiceField(choices=GeneratedReport.FORMAT_CHOICES, default='pdf')
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    parameters = serializers.JSONField(required=False, default=dict)


class ScheduledReportSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')

    class Meta:
        model = ScheduledReport
        fields = '__all__'
        read_only_fields = ['created_by', 'last_run', 'run_count']

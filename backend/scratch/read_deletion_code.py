import inspect
from django.db.models.deletion import Collector

print("Collector.collect source code:")
print(inspect.getsource(Collector.collect))

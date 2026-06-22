import inspect
from django.db.models.deletion import get_candidate_relations_to_delete

print("get_candidate_relations_to_delete source code:")
print(inspect.getsource(get_candidate_relations_to_delete))

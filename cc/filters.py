import django_filters
from .models import Unimod
from rest_framework import filters

class UnimodFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='startswith')
    definition = django_filters.CharFilter(field_name='definition', lookup_expr='icontains')

    class Meta:
        model = Unimod
        fields = ['name', 'definition']

class UnimodSearchFilter(filters.SearchFilter):
    def get_search_fields(self, view, request):
        search_type = request.query_params.get('search_type', None)
        if search_type == 'contains':
            return ['name', 'definition']
        return super().get_search_fields(view, request)

class MSUniqueVocabulariesSearchFilter(filters.SearchFilter):
    def get_search_fields(self,view, request):
        search_type = request.query_params.get('search_type', None)
        if search_type == 'contains':
            return ['name']
        return super().get_search_fields(view, request)

class HumanDiseaseSearchFilter(filters.SearchFilter):
    def get_search_fields(self, view, request):
        search_type = request.query_params.get('search_type', None)
        if search_type == 'contains':
            return ['identifier', 'synonyms', 'acronym']
        return super().get_search_fields(view, request)

class TissueSearchFilter(filters.SearchFilter):
    def get_search_fields(self, view, request):
        search_type = request.query_params.get('search_type', None)
        if search_type == 'contains':
            return ['identifier', 'synonyms']
        return super().get_search_fields(view, request)

class SubcellularLocationSearchFilter(filters.SearchFilter):
    def get_search_fields(self, view, request):
        search_type = request.query_params.get('search_type', None)
        if search_type == 'contains':
            return ['location_identifier', 'synonyms']
        return super().get_search_fields(view, request)

class SpeciesSearchFilter(filters.SearchFilter):
    def get_search_fields(self, view, request):
        search_type = request.query_params.get('search_type', None)
        if search_type == 'contains':
            return ['common_name', 'official_name']
        return super().get_search_fields(view, request)
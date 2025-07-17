from django.contrib import admin
from .models import (
    CellType, MondoDisease, UberonAnatomy, NCBITaxonomy, 
    ChEBICompound, PSIMSOntology, ProtocolStepSuggestionCache
)

# Register your models here.

@admin.register(CellType)
class CellTypeAdmin(admin.ModelAdmin):
    """Admin interface for CellType model."""
    
    list_display = ['name', 'identifier', 'cell_line', 'organism', 'tissue_origin', 'disease_context']
    list_filter = ['cell_line', 'organism', 'tissue_origin']
    search_fields = ['name', 'identifier', 'synonyms', 'description']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('identifier', 'name', 'description')
        }),
        ('Classification', {
            'fields': ('cell_line', 'organism', 'tissue_origin', 'disease_context')
        }),
        ('Ontology References', {
            'fields': ('accession', 'synonyms')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(MondoDisease)
class MondoDiseaseAdmin(admin.ModelAdmin):
    """Admin interface for MONDO Disease ontology."""
    
    list_display = ['name', 'identifier', 'obsolete']
    list_filter = ['obsolete']
    search_fields = ['name', 'identifier', 'synonyms', 'definition']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('identifier', 'name', 'definition')
        }),
        ('Ontology Data', {
            'fields': ('synonyms', 'xrefs', 'parent_terms')
        }),
        ('Status', {
            'fields': ('obsolete', 'replacement_term')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(UberonAnatomy)
class UberonAnatomyAdmin(admin.ModelAdmin):
    """Admin interface for UBERON Anatomy ontology."""
    
    list_display = ['name', 'identifier', 'obsolete']
    list_filter = ['obsolete']
    search_fields = ['name', 'identifier', 'synonyms', 'definition']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('identifier', 'name', 'definition')
        }),
        ('Ontology Data', {
            'fields': ('synonyms', 'xrefs', 'parent_terms', 'part_of', 'develops_from')
        }),
        ('Status', {
            'fields': ('obsolete', 'replacement_term')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(NCBITaxonomy)
class NCBITaxonomyAdmin(admin.ModelAdmin):
    """Admin interface for NCBI Taxonomy."""
    
    list_display = ['scientific_name', 'common_name', 'tax_id', 'rank']
    list_filter = ['rank']
    search_fields = ['scientific_name', 'common_name', 'synonyms']
    ordering = ['scientific_name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('tax_id', 'scientific_name', 'common_name', 'rank')
        }),
        ('Taxonomy', {
            'fields': ('parent_tax_id', 'lineage', 'synonyms')
        }),
        ('Genetic Codes', {
            'fields': ('genetic_code', 'mitochondrial_genetic_code'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ChEBICompound)
class ChEBICompoundAdmin(admin.ModelAdmin):
    """Admin interface for ChEBI compounds."""
    
    list_display = ['name', 'identifier', 'formula', 'obsolete']
    list_filter = ['obsolete']
    search_fields = ['name', 'identifier', 'synonyms', 'formula']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('identifier', 'name', 'definition')
        }),
        ('Chemical Properties', {
            'fields': ('formula', 'mass', 'charge', 'inchi', 'smiles')
        }),
        ('Ontology Data', {
            'fields': ('synonyms', 'parent_terms', 'roles')
        }),
        ('Status', {
            'fields': ('obsolete', 'replacement_term')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PSIMSOntology)
class PSIMSOntologyAdmin(admin.ModelAdmin):
    """Admin interface for PSI-MS ontology."""
    
    list_display = ['name', 'identifier', 'category', 'obsolete']
    list_filter = ['category', 'obsolete']
    search_fields = ['name', 'identifier', 'synonyms', 'definition']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('identifier', 'name', 'definition', 'category')
        }),
        ('Ontology Data', {
            'fields': ('synonyms', 'parent_terms')
        }),
        ('Status', {
            'fields': ('obsolete', 'replacement_term')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ProtocolStepSuggestionCache)
class ProtocolStepSuggestionCacheAdmin(admin.ModelAdmin):
    """Admin interface for Protocol Step Suggestion Cache."""
    
    list_display = ['step', 'analyzer_type', 'is_valid', 'created_at', 'updated_at', 'cache_age']
    list_filter = ['analyzer_type', 'is_valid', 'created_at', 'updated_at']
    search_fields = ['step__step_description', 'step__step_name', 'analyzer_type']
    ordering = ['-updated_at']
    readonly_fields = ['created_at', 'updated_at', 'step_content_hash', 'cache_age', 'cache_size']
    
    fieldsets = (
        ('Cache Information', {
            'fields': ('step', 'analyzer_type', 'is_valid')
        }),
        ('Cache Content', {
            'fields': ('sdrf_suggestions', 'analysis_metadata', 'extracted_terms'),
            'classes': ('collapse',)
        }),
        ('Cache Management', {
            'fields': ('step_content_hash', 'cache_age', 'cache_size'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['invalidate_cache', 'cleanup_expired_cache']
    
    def cache_age(self, obj):
        """Show cache age in human-readable format."""
        from django.utils import timezone
        delta = timezone.now() - obj.updated_at
        if delta.days > 0:
            return f"{delta.days} day{'s' if delta.days != 1 else ''}"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''}"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            return "Just now"
    cache_age.short_description = 'Cache Age'
    
    def cache_size(self, obj):
        """Show estimated cache size."""
        import json
        try:
            suggestions_size = len(json.dumps(obj.sdrf_suggestions))
            metadata_size = len(json.dumps(obj.analysis_metadata))
            terms_size = len(json.dumps(obj.extracted_terms))
            total_size = suggestions_size + metadata_size + terms_size
            
            if total_size > 1024:
                return f"{total_size / 1024:.1f} KB"
            else:
                return f"{total_size} bytes"
        except:
            return "Unknown"
    cache_size.short_description = 'Cache Size'
    
    def invalidate_cache(self, request, queryset):
        """Invalidate selected cache entries."""
        count = 0
        for cache_entry in queryset:
            cache_entry.invalidate()
            count += 1
        
        self.message_user(
            request,
            f"Successfully invalidated {count} cache entries."
        )
    invalidate_cache.short_description = "Invalidate selected cache entries"
    
    def cleanup_expired_cache(self, request, queryset):
        """Clean up expired cache entries."""
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=30)
        deleted_count = ProtocolStepSuggestionCache.objects.filter(
            created_at__lt=cutoff_date
        ).delete()[0]
        
        self.message_user(
            request,
            f"Successfully cleaned up {deleted_count} expired cache entries (older than 30 days)."
        )
    cleanup_expired_cache.short_description = "Clean up expired cache entries (30+ days)"

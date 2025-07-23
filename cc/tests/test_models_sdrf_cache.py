"""
Tests for SDRF suggestion cache system: ProtocolStepSuggestionCache
"""
import hashlib
from datetime import datetime, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from cc.models import (
    ProtocolStepSuggestionCache, ProtocolStep, ProtocolModel, 
    ProtocolSection, Project
)


class ProtocolStepSuggestionCacheModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(
            project_name='Test Project',
            owner=self.user
        )
        
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Test Protocol',
            protocol_id=1001,
            user=self.user
        )
        
        self.section = ProtocolSection.objects.create(
            protocol=self.protocol,
            section_description='Test Section'
        )
        
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_id=1,
            step_description='Add 100μL of sample to the reaction tube',
            step_section=self.section
        )
    
    def test_cache_creation(self):
        """Test basic cache creation"""
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            sdrf_suggestions={'sample_type': 'serum', 'organism': 'human'},
            analysis_metadata={'confidence': 0.85, 'processing_time': 2.5},
            extracted_terms=['sample', 'tube', 'reaction'],
            step_content_hash='abc123def456'
        )
        
        self.assertEqual(cache.step, self.step)
        self.assertEqual(cache.analyzer_type, 'standard_nlp')
        self.assertEqual(cache.sdrf_suggestions, {'sample_type': 'serum', 'organism': 'human'})
        self.assertEqual(cache.analysis_metadata, {'confidence': 0.85, 'processing_time': 2.5})
        self.assertEqual(cache.extracted_terms, ['sample', 'tube', 'reaction'])
        self.assertEqual(cache.step_content_hash, 'abc123def456')
        self.assertTrue(cache.is_valid)
        self.assertIsNotNone(cache.created_at)
        self.assertIsNotNone(cache.updated_at)
    
    def test_cache_str_representation(self):
        """Test cache string representation"""
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='mcp_claude',
            step_content_hash='test123'
        )
        
        expected_str = f"Cache for step {self.step.id} (mcp_claude)"
        self.assertEqual(str(cache), expected_str)
    
    def test_analyzer_type_choices(self):
        """Test all analyzer type choices"""
        analyzer_types = ['standard_nlp', 'mcp_claude', 'anthropic_claude']
        
        for analyzer_type in analyzer_types:
            cache = ProtocolStepSuggestionCache.objects.create(
                step=self.step,
                analyzer_type=analyzer_type,
                step_content_hash=f'hash_{analyzer_type}'
            )
            self.assertEqual(cache.analyzer_type, analyzer_type)
    
    def test_unique_constraint(self):
        """Test unique constraint on step and analyzer_type"""
        # Create first cache
        ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            step_content_hash='hash1'
        )
        
        # Try to create duplicate - should update existing
        cache2 = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            step_content_hash='hash2'
        )
        
        # Should only have one cache entry
        caches = ProtocolStepSuggestionCache.objects.filter(
            step=self.step,
            analyzer_type='standard_nlp'
        )
        self.assertEqual(caches.count(), 1)
    
    def test_get_cache_key_method(self):
        """Test get_cache_key class method"""
        key = ProtocolStepSuggestionCache.get_cache_key(123, 'standard_nlp')
        self.assertEqual(key, 'step_123_standard_nlp')
        
        key2 = ProtocolStepSuggestionCache.get_cache_key(456, 'mcp_claude')
        self.assertEqual(key2, 'step_456_mcp_claude')
    
    def test_get_step_content_hash_method(self):
        """Test get_step_content_hash method"""
        cache = ProtocolStepSuggestionCache(
            step=self.step,
            analyzer_type='standard_nlp'
        )
        
        test_description = "Test step description"
        hash_result = cache.get_step_content_hash(test_description)
        
        # Should be SHA256 hash
        expected_hash = hashlib.sha256(test_description.encode('utf-8')).hexdigest()
        self.assertEqual(hash_result, expected_hash)
        self.assertEqual(len(hash_result), 64)  # SHA256 produces 64 character hex
    
    def test_is_cache_valid_method(self):
        """Test is_cache_valid method"""
        # Create cache with current step content hash
        current_hash = hashlib.sha256(self.step.step_description.encode('utf-8')).hexdigest()
        
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            step_content_hash=current_hash,
            is_valid=True
        )
        
        # Should be valid
        self.assertTrue(cache.is_cache_valid())
        
        # Mark as invalid
        cache.is_valid = False
        cache.save()
        self.assertFalse(cache.is_cache_valid())
        
        # Reset validity but change step content
        cache.is_valid = True
        cache.step_content_hash = 'outdated_hash'
        cache.save()
        
        # Should be invalid due to content mismatch
        self.assertFalse(cache.is_cache_valid())
    
    def test_invalidate_method(self):
        """Test invalidate method"""
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            is_valid=True,
            step_content_hash='test_hash'
        )
        
        # Verify initially valid
        self.assertTrue(cache.is_valid)
        
        # Invalidate
        cache.invalidate()
        
        # Refresh and check
        cache.refresh_from_db()
        self.assertFalse(cache.is_valid)
    
    def test_get_cached_suggestions_method(self):
        """Test get_cached_suggestions class method"""
        # Create valid cache
        current_hash = hashlib.sha256(self.step.step_description.encode('utf-8')).hexdigest()
        suggestions = {'sample_type': 'serum', 'organism': 'human'}
        metadata = {'confidence': 0.9}
        terms = ['sample', 'serum']
        
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            sdrf_suggestions=suggestions,
            analysis_metadata=metadata,
            extracted_terms=terms,
            step_content_hash=current_hash,
            is_valid=True
        )
        
        # Should return cached data
        result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'standard_nlp'
        )
        
        self.assertIsNotNone(result)
        self.assertTrue(result['success'])
        self.assertEqual(result['step_id'], self.step.id)
        self.assertEqual(result['sdrf_suggestions'], suggestions)
        self.assertEqual(result['analysis_metadata'], metadata)
        self.assertEqual(result['extracted_terms'], terms)
        self.assertTrue(result['cached'])
        self.assertIn('cache_created_at', result)
        self.assertIn('cache_updated_at', result)
    
    def test_get_cached_suggestions_invalid_cache(self):
        """Test get_cached_suggestions with invalid cache"""
        # Create invalid cache (wrong content hash)
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            step_content_hash='outdated_hash',
            is_valid=True
        )
        
        # Should return None and delete invalid cache
        result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'standard_nlp'
        )
        
        self.assertIsNone(result)
        
        # Cache should be deleted
        with self.assertRaises(ProtocolStepSuggestionCache.DoesNotExist):
            ProtocolStepSuggestionCache.objects.get(id=cache.id)
    
    def test_get_cached_suggestions_not_exists(self):
        """Test get_cached_suggestions when cache doesn't exist"""
        result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'nonexistent_analyzer'
        )
        
        self.assertIsNone(result)
    
    def test_cache_suggestions_method(self):
        """Test cache_suggestions class method"""
        suggestions_data = {
            'sdrf_suggestions': {'sample_type': 'plasma', 'organism': 'mouse'},
            'analysis_metadata': {'confidence': 0.95, 'analyzer_version': '1.2.3'},
            'extracted_terms': ['plasma', 'mouse', 'sample']
        }
        
        # Cache the suggestions
        cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'mcp_claude', suggestions_data
        )
        
        self.assertIsNotNone(cache)
        self.assertEqual(cache.step, self.step)
        self.assertEqual(cache.analyzer_type, 'mcp_claude')
        self.assertEqual(cache.sdrf_suggestions, suggestions_data['sdrf_suggestions'])
        self.assertEqual(cache.analysis_metadata, suggestions_data['analysis_metadata'])
        self.assertEqual(cache.extracted_terms, suggestions_data['extracted_terms'])
        self.assertTrue(cache.is_valid)
        
        # Verify content hash is correct
        expected_hash = hashlib.sha256(self.step.step_description.encode('utf-8')).hexdigest()
        self.assertEqual(cache.step_content_hash, expected_hash)
    
    def test_cache_suggestions_update_existing(self):
        """Test cache_suggestions updating existing cache"""
        # Create initial cache
        initial_cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='anthropic_claude',
            sdrf_suggestions={'old': 'data'},
            step_content_hash='old_hash'
        )
        
        initial_id = initial_cache.id
        
        # Update with new data
        new_data = {
            'sdrf_suggestions': {'new': 'data'},
            'analysis_metadata': {'updated': True}
        }
        
        updated_cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'anthropic_claude', new_data
        )
        
        # Should update existing cache, not create new one
        self.assertEqual(updated_cache.id, initial_id)
        self.assertEqual(updated_cache.sdrf_suggestions, {'new': 'data'})
        self.assertEqual(updated_cache.analysis_metadata, {'updated': True})
        
        # Should only have one cache entry
        cache_count = ProtocolStepSuggestionCache.objects.filter(
            step=self.step,
            analyzer_type='anthropic_claude'
        ).count()
        self.assertEqual(cache_count, 1)
    
    def test_cache_suggestions_nonexistent_step(self):
        """Test cache_suggestions with nonexistent step"""
        result = ProtocolStepSuggestionCache.cache_suggestions(
            99999, 'standard_nlp', {'test': 'data'}
        )
        
        self.assertIsNone(result)
    
    def test_invalidate_step_cache_method(self):
        """Test invalidate_step_cache class method"""
        # Create multiple caches for the same step with different analyzers
        cache1 = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            is_valid=True,
            step_content_hash='hash1'
        )
        
        cache2 = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='mcp_claude',
            is_valid=True,
            step_content_hash='hash2'
        )
        
        # Create cache for different step (should not be affected)
        other_step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_id=2,
            step_description='Different step',
            step_section=self.section
        )
        
        other_cache = ProtocolStepSuggestionCache.objects.create(
            step=other_step,
            analyzer_type='standard_nlp',
            is_valid=True,
            step_content_hash='other_hash'
        )
        
        # Invalidate all caches for self.step
        ProtocolStepSuggestionCache.invalidate_step_cache(self.step.id)
        
        # Refresh from database
        cache1.refresh_from_db()
        cache2.refresh_from_db()
        other_cache.refresh_from_db()
        
        # Caches for self.step should be invalid
        self.assertFalse(cache1.is_valid)
        self.assertFalse(cache2.is_valid)
        
        # Cache for other step should still be valid
        self.assertTrue(other_cache.is_valid)
    
    def test_cleanup_expired_cache_method(self):
        """Test cleanup_expired_cache class method"""
        from django.utils import timezone
        
        # Create old cache entries
        old_time = timezone.now() - timedelta(days=35)
        
        old_cache1 = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            step_content_hash='old1'
        )
        old_cache1.created_at = old_time
        old_cache1.save()
        
        old_cache2 = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='mcp_claude',
            step_content_hash='old2'
        )
        old_cache2.created_at = old_time
        old_cache2.save()
        
        # Create recent cache
        recent_cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='anthropic_claude',
            step_content_hash='recent'
        )
        
        # Verify all exist
        self.assertEqual(ProtocolStepSuggestionCache.objects.count(), 3)
        
        # Clean up caches older than 30 days
        ProtocolStepSuggestionCache.cleanup_expired_cache(days_old=30)
        
        # Should only have recent cache
        remaining_caches = ProtocolStepSuggestionCache.objects.all()
        self.assertEqual(remaining_caches.count(), 1)
        self.assertEqual(remaining_caches.first().id, recent_cache.id)
    
    def test_cache_ordering(self):
        """Test cache ordering by -updated_at"""
        cache1 = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            step_content_hash='cache1'
        )
        
        # Simulate time passing
        import time
        time.sleep(0.1)
        
        cache2 = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='mcp_claude',
            step_content_hash='cache2'
        )
        
        caches = list(ProtocolStepSuggestionCache.objects.all())
        self.assertEqual(caches[0], cache2)  # Most recent first
        self.assertEqual(caches[1], cache1)


class ProtocolStepSuggestionCacheIntegrationTest(TestCase):
    """Integration tests for cache with protocol step updates"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Integration Test Protocol',
            protocol_id=2001,
            user=self.user
        )
        
        self.section = ProtocolSection.objects.create(
            protocol=self.protocol,
            section_description='Integration Section'
        )
        
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_id=1,
            step_description='Original step description',
            step_section=self.section
        )
    
    def test_cache_invalidation_on_step_update(self):
        """Test that cache is invalidated when step description changes"""
        # Create cache
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            is_valid=True,
            step_content_hash=hashlib.sha256(self.step.step_description.encode('utf-8')).hexdigest()
        )
        
        # Verify cache is valid
        self.assertTrue(cache.is_valid)
        
        # Update step description (this should trigger signal)
        self.step.step_description = 'Updated step description'
        self.step.save(update_fields=['step_description'])
        
        # Cache should be invalidated
        cache.refresh_from_db()
        self.assertFalse(cache.is_valid)
    
    def test_cache_not_invalidated_on_other_field_update(self):
        """Test that cache is not invalidated when other fields change"""
        # Create cache
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            is_valid=True,
            step_content_hash=hashlib.sha256(self.step.step_description.encode('utf-8')).hexdigest()
        )
        
        # Update other field
        self.step.step_duration = 30
        self.step.save(update_fields=['step_duration'])
        
        # Cache should still be valid
        cache.refresh_from_db()
        self.assertTrue(cache.is_valid)
    
    def test_complete_cache_workflow(self):
        """Test complete cache workflow from creation to retrieval"""
        # 1. Create initial cache
        initial_data = {
            'sdrf_suggestions': {
                'organism': 'Homo sapiens',
                'sample_type': 'serum',
                'instrument_model': 'Orbitrap Fusion'
            },
            'analysis_metadata': {
                'confidence': 0.87,
                'processing_time': 1.23,
                'analyzer_version': '2.1.0'
            },
            'extracted_terms': ['serum', 'sample', 'analysis']
        }
        
        cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'mcp_claude', initial_data
        )
        
        self.assertIsNotNone(cache)
        
        # 2. Retrieve cached suggestions
        cached_result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'mcp_claude'
        )
        
        self.assertIsNotNone(cached_result)
        self.assertTrue(cached_result['success'])
        self.assertEqual(cached_result['sdrf_suggestions'], initial_data['sdrf_suggestions'])
        self.assertEqual(cached_result['analysis_metadata'], initial_data['analysis_metadata'])
        self.assertEqual(cached_result['extracted_terms'], initial_data['extracted_terms'])
        
        # 3. Update step description (invalidates cache)
        self.step.step_description = 'Modified step for cache testing'
        self.step.save(update_fields=['step_description'])
        
        # 4. Try to retrieve cache (should return None due to invalidation)
        invalidated_result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'mcp_claude'
        )
        
        self.assertIsNone(invalidated_result)
        
        # 5. Create new cache with updated data
        updated_data = {
            'sdrf_suggestions': {
                'organism': 'Mus musculus',
                'sample_type': 'plasma'
            },
            'analysis_metadata': {
                'confidence': 0.92,
                'processing_time': 0.98
            }
        }
        
        new_cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'mcp_claude', updated_data
        )
        
        # 6. Retrieve updated cache
        final_result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'mcp_claude'
        )
        
        self.assertIsNotNone(final_result)
        self.assertEqual(final_result['sdrf_suggestions'], updated_data['sdrf_suggestions'])
        self.assertEqual(final_result['analysis_metadata'], updated_data['analysis_metadata'])
    
    def test_multiple_analyzer_caches(self):
        """Test caching with multiple analyzers for same step"""
        analyzers = ['standard_nlp', 'mcp_claude', 'anthropic_claude']
        
        # Create cache for each analyzer
        for analyzer in analyzers:
            data = {
                'sdrf_suggestions': {f'{analyzer}_suggestion': f'{analyzer}_value'},
                'analysis_metadata': {'analyzer': analyzer}
            }
            
            cache = ProtocolStepSuggestionCache.cache_suggestions(
                self.step.id, analyzer, data
            )
            self.assertIsNotNone(cache)
        
        # Verify each analyzer has its own cache
        for analyzer in analyzers:
            result = ProtocolStepSuggestionCache.get_cached_suggestions(
                self.step.id, analyzer
            )
            self.assertIsNotNone(result)
            self.assertEqual(result['analysis_metadata']['analyzer'], analyzer)
        
        # Update step description (should invalidate all caches)
        self.step.step_description = 'Updated for multi-analyzer test'
        self.step.save(update_fields=['step_description'])
        
        # All caches should be invalidated
        for analyzer in analyzers:
            result = ProtocolStepSuggestionCache.get_cached_suggestions(
                self.step.id, analyzer
            )
            self.assertIsNone(result)
    
    def test_cache_performance_simulation(self):
        """Test cache performance with realistic data volumes"""
        # Create multiple steps
        steps = []
        for i in range(10):
            step = ProtocolStep.objects.create(
                protocol=self.protocol,
                step_id=i + 2,
                step_description=f'Performance test step {i + 1}',
                step_section=self.section
            )
            steps.append(step)
        
        # Create caches for all steps and analyzers
        analyzers = ['standard_nlp', 'mcp_claude', 'anthropic_claude']
        created_caches = []
        
        for step in steps:
            for analyzer in analyzers:
                suggestions = {
                    'sample_type': f'sample_{step.step_id}',
                    'organism': 'test organism',
                    'confidence_score': 0.85 + (step.step_id * 0.01)
                }
                
                cache = ProtocolStepSuggestionCache.cache_suggestions(
                    step.id, analyzer, {'sdrf_suggestions': suggestions}
                )
                created_caches.append(cache.id)
        
        # Verify all caches were created
        total_caches = ProtocolStepSuggestionCache.objects.count()
        self.assertEqual(total_caches, len(steps) * len(analyzers))
        
        # Test bulk retrieval performance
        retrieved_count = 0
        for step in steps:
            for analyzer in analyzers:
                result = ProtocolStepSuggestionCache.get_cached_suggestions(
                    step.id, analyzer
                )
                if result:
                    retrieved_count += 1
        
        self.assertEqual(retrieved_count, len(steps) * len(analyzers))
        
        # Test bulk invalidation
        for step in steps[::2]:  # Invalidate every other step
            ProtocolStepSuggestionCache.invalidate_step_cache(step.id)
        
        # Verify partial invalidation
        valid_caches = ProtocolStepSuggestionCache.objects.filter(is_valid=True).count()
        expected_valid = len(steps[1::2]) * len(analyzers)  # Odd-indexed steps remain valid
        self.assertEqual(valid_caches, expected_valid)


class ProtocolStepSuggestionCacheEdgeCasesTest(TestCase):
    """Test edge cases and error conditions"""
    
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.protocol = ProtocolModel.objects.create(
            protocol_title='Edge Case Protocol',
            protocol_id=3001,
            user=self.user
        )
        
        self.section = ProtocolSection.objects.create(
            protocol=self.protocol,
            section_description='Edge Case Section'
        )
        
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_id=1,
            step_description='Edge case step',
            step_section=self.section
        )
    
    def test_empty_suggestions_data(self):
        """Test caching with empty or minimal data"""
        # Empty suggestions
        empty_cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'standard_nlp', {}
        )
        
        self.assertIsNotNone(empty_cache)
        self.assertEqual(empty_cache.sdrf_suggestions, {})
        self.assertEqual(empty_cache.analysis_metadata, {})
        self.assertEqual(empty_cache.extracted_terms, [])
        
        # Retrieve empty cache
        result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'standard_nlp'
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(result['sdrf_suggestions'], {})
    
    def test_large_suggestions_data(self):
        """Test caching with large data structures"""
        # Create large suggestions data
        large_suggestions = {}
        for i in range(1000):
            large_suggestions[f'key_{i}'] = f'value_{i}' * 10  # 70+ chars per value
        
        large_metadata = {
            'large_list': list(range(1000)),
            'large_dict': {f'item_{i}': i * 2 for i in range(100)}
        }
        
        large_terms = [f'term_{i}' for i in range(500)]
        
        cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'standard_nlp', {
                'sdrf_suggestions': large_suggestions,
                'analysis_metadata': large_metadata,
                'extracted_terms': large_terms
            }
        )
        
        self.assertIsNotNone(cache)
        
        # Retrieve and verify large data
        result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'standard_nlp'
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result['sdrf_suggestions']), 1000)
        self.assertEqual(len(result['extracted_terms']), 500)
        self.assertEqual(result['analysis_metadata']['large_list'], list(range(1000)))
    
    def test_unicode_and_special_characters(self):
        """Test caching with unicode and special characters"""
        unicode_data = {
            'sdrf_suggestions': {
                'organism': 'Hömo säpiens',
                'sample_type': 'Cérebro-spinal fluid',
                'special_chars': '!@#$%^&*()_+-={}[]|\\:";\'<>?,./',
                'emoji': '🧬🔬🧪',
                'chinese': '人类基因组',
                'arabic': 'الحمض النووي'
            },
            'extracted_terms': ['protéine', 'génome', '🧬', '特殊字符']
        }
        
        cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'mcp_claude', unicode_data
        )
        
        self.assertIsNotNone(cache)
        
        # Retrieve and verify unicode data
        result = ProtocolStepSuggestionCache.get_cached_suggestions(
            self.step.id, 'mcp_claude'
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(result['sdrf_suggestions']['organism'], 'Hömo säpiens')
        self.assertEqual(result['sdrf_suggestions']['emoji'], '🧬🔬🧪')
        self.assertIn('protéine', result['extracted_terms'])
    
    def test_null_and_none_values(self):
        """Test handling of null and None values"""
        # Test with None values (should be converted to default empty values)
        cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'standard_nlp', {
                'sdrf_suggestions': None,
                'analysis_metadata': None,
                'extracted_terms': None
            }
        )
        
        self.assertIsNotNone(cache)
        # None values should be converted to empty defaults
        self.assertEqual(cache.sdrf_suggestions, {})
        self.assertEqual(cache.analysis_metadata, {})
        self.assertEqual(cache.extracted_terms, [])
    
    def test_concurrent_cache_operations(self):
        """Test concurrent cache operations (simulation)"""
        # Simulate concurrent cache creation/update
        initial_cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'anthropic_claude', {'version': 'v1'}
        )
        
        # Simulate another process updating the same cache
        updated_cache = ProtocolStepSuggestionCache.cache_suggestions(
            self.step.id, 'anthropic_claude', {'version': 'v2'}
        )
        
        # Should be the same cache object (updated, not duplicated)
        self.assertEqual(initial_cache.id, updated_cache.id)
        self.assertEqual(updated_cache.sdrf_suggestions, {'version': 'v2'})
        
        # Should only have one cache entry
        cache_count = ProtocolStepSuggestionCache.objects.filter(
            step=self.step,
            analyzer_type='anthropic_claude'
        ).count()
        self.assertEqual(cache_count, 1)
    
    def test_step_deletion_cascade(self):
        """Test what happens when protocol step is deleted"""
        # Create cache
        cache = ProtocolStepSuggestionCache.objects.create(
            step=self.step,
            analyzer_type='standard_nlp',
            step_content_hash='test_hash'
        )
        
        cache_id = cache.id
        
        # Delete the step (should cascade delete the cache)
        self.step.delete()
        
        # Cache should be deleted
        with self.assertRaises(ProtocolStepSuggestionCache.DoesNotExist):
            ProtocolStepSuggestionCache.objects.get(id=cache_id)
    
    def test_database_indexes_effectiveness(self):
        """Test that database indexes are effective for common queries"""
        # Create multiple caches for testing index usage
        steps = []
        for i in range(20):
            step = ProtocolStep.objects.create(
                protocol=self.protocol,
                step_id=i + 2,
                step_description=f'Index test step {i}',
                step_section=self.section
            )
            steps.append(step)
        
        analyzers = ['standard_nlp', 'mcp_claude', 'anthropic_claude']
        
        # Create caches
        for step in steps:
            for analyzer in analyzers:
                ProtocolStepSuggestionCache.objects.create(
                    step=step,
                    analyzer_type=analyzer,
                    step_content_hash=f'hash_{step.id}_{analyzer}',
                    is_valid=(step.step_id % 2 == 0)  # Half valid, half invalid
                )
        
        # Test queries that should use indexes
        
        # 1. Query by step and analyzer_type (compound unique index)
        specific_cache = ProtocolStepSuggestionCache.objects.filter(
            step=steps[0],
            analyzer_type='standard_nlp'
        ).first()
        self.assertIsNotNone(specific_cache)
        
        # 2. Query by step and is_valid (should use step index)
        valid_caches = ProtocolStepSuggestionCache.objects.filter(
            step=steps[0],
            is_valid=True
        )
        self.assertGreater(valid_caches.count(), 0)
        
        # 3. Query by created_at (should use created_at index)
        recent_caches = ProtocolStepSuggestionCache.objects.filter(
            created_at__gte=timezone.now() - timedelta(hours=1)
        )
        self.assertEqual(recent_caches.count(), len(steps) * len(analyzers))
        
        # 4. Ordering query (should use ordering index -updated_at)
        ordered_caches = ProtocolStepSuggestionCache.objects.all()[:10]
        self.assertEqual(len(list(ordered_caches)), 10)
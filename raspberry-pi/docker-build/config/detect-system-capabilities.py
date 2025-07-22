#!/usr/bin/env python3
"""
System Capability Detection for CUPCAKE Pi Deployments
Detects system specifications and recommends optimal Whisper.cpp model and settings
"""

import os
import sys
import json
import psutil
import platform
import subprocess
from pathlib import Path


class SystemCapabilityDetector:
    """Detects system capabilities for optimal CUPCAKE configuration"""
    
    def __init__(self):
        self.system_info = self._gather_system_info()
        
    def _gather_system_info(self):
        """Gather comprehensive system information"""
        info = {
            'platform': platform.platform(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
            'total_memory_mb': psutil.virtual_memory().total // (1024 * 1024),
            'cpu_count': psutil.cpu_count(logical=True),
            'cpu_count_physical': psutil.cpu_count(logical=False),
            'cpu_freq_max': None,
            'is_raspberry_pi': False,
            'pi_model': None,
            'pi_revision': None
        }
        
        # Get CPU frequency if available
        try:
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                info['cpu_freq_max'] = cpu_freq.max
        except:
            pass
            
        # Detect Raspberry Pi
        try:
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read()
                
            if 'Raspberry Pi' in cpuinfo or 'BCM2' in cpuinfo:
                info['is_raspberry_pi'] = True
                
                # Extract model info
                for line in cpuinfo.split('\n'):
                    if line.startswith('Model'):
                        info['pi_model'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Revision'):
                        info['pi_revision'] = line.split(':', 1)[1].strip()
                        
        except FileNotFoundError:
            pass
            
        return info
    
    def get_system_tier(self):
        """Determine system performance tier: low, medium, or high"""
        memory_mb = self.system_info['total_memory_mb']
        cpu_count = self.system_info['cpu_count']
        is_pi = self.system_info['is_raspberry_pi']
        
        # Pi-specific logic (prioritize based on known Pi models)
        if is_pi:
            if memory_mb <= 1024:  # Pi Zero, Pi 3 A+, older models
                return 'low'
            elif memory_mb <= 2048:  # Pi 3 B+, Pi 4 2GB
                return 'medium' if cpu_count >= 4 else 'low'
            elif memory_mb <= 4096:  # Pi 4 4GB, Pi 5 4GB
                return 'medium'
            else:  # Pi 4 8GB, Pi 5 8GB
                return 'high'
        
        # Generic system logic
        if memory_mb <= 2048 or cpu_count <= 2:
            return 'low'
        elif memory_mb <= 4096 or cpu_count <= 4:
            return 'medium'
        else:
            return 'high'
    
    def get_whisper_config(self):
        """Get optimal Whisper.cpp configuration for this system"""
        tier = self.get_system_tier()
        memory_mb = self.system_info['total_memory_mb']
        cpu_count = self.system_info['cpu_count']
        
        # Base paths
        whisper_base = "/opt/whisper.cpp"
        models_base = f"{whisper_base}/models"
        
        configs = {
            'low': {
                'model': 'ggml-tiny.en.bin',
                'model_path': f"{models_base}/ggml-tiny.en.bin",
                'thread_count': min(2, cpu_count),
                'recommended_models': ['tiny.en'],
                'description': 'Tiny model for low-power systems (< 2GB RAM)'
            },
            'medium': {
                'model': 'ggml-base.en.bin',
                'model_path': f"{models_base}/ggml-base.en.bin",
                'thread_count': min(4, cpu_count),
                'recommended_models': ['base.en', 'tiny.en'],
                'description': 'Base model for medium-power systems (2-4GB RAM)'
            },
            'high': {
                'model': 'ggml-small.en.bin', 
                'model_path': f"{models_base}/ggml-small.en.bin",
                'thread_count': min(6, cpu_count),
                'recommended_models': ['small.en', 'base.en', 'tiny.en'],
                'description': 'Small model for high-power systems (4GB+ RAM)'
            }
        }
        
        config = configs[tier].copy()
        config.update({
            'binary_path': f"{whisper_base}/build/bin/whisper-cli",
            'models_directory': models_base,
            'system_tier': tier
        })
        
        return config
    
    def get_django_env_vars(self):
        """Get Django environment variables for CUPCAKE settings"""
        whisper_config = self.get_whisper_config()
        
        return {
            'WHISPERCPP_PATH': whisper_config['binary_path'],
            'WHISPERCPP_DEFAULT_MODEL': whisper_config['model_path'],
            'WHISPERCPP_THREAD_COUNT': str(whisper_config['thread_count'])
        }
    
    def get_system_optimizations(self):
        """Get system-specific optimization recommendations"""
        tier = self.get_system_tier()
        memory_mb = self.system_info['total_memory_mb']
        is_pi = self.system_info['is_raspberry_pi']
        
        optimizations = {
            'postgresql': {
                'shared_buffers': '128MB' if memory_mb < 2048 else '256MB',
                'effective_cache_size': f"{memory_mb // 4}MB",
                'work_mem': '4MB' if memory_mb < 2048 else '8MB',
                'max_connections': 50 if memory_mb < 2048 else 100
            },
            'redis': {
                'maxmemory': f"{min(256, memory_mb // 8)}MB",
                'maxmemory_policy': 'allkeys-lru'
            },
            'django': {
                'DEBUG': False,
                'ALLOWED_HOSTS': ['*'] if is_pi else ['localhost'],
                'USE_WHISPER': True,
                'USE_LLM': tier in ['medium', 'high'],  # Only enable LLM on capable systems
                'USE_OCR': True,
                'RQ_DEFAULT_TIMEOUT': 180 if tier == 'low' else 360
            },
            'system': {
                'swap_size': '1GB' if memory_mb < 2048 else '2GB',
                'gpu_memory': 64 if is_pi and memory_mb <= 1024 else 128,
                'enable_zram': memory_mb < 2048
            }
        }
        
        return optimizations
    
    def generate_config_files(self, output_dir="/opt/cupcake/config"):
        """Generate configuration files based on system capabilities"""
        os.makedirs(output_dir, exist_ok=True)
        
        # Django environment file
        env_vars = self.get_django_env_vars()
        optimizations = self.get_system_optimizations()
        
        env_content = "# Auto-generated CUPCAKE environment configuration\n"
        env_content += f"# Generated for {self.system_info['pi_model'] or 'system'} "
        env_content += f"({self.get_system_tier()} tier)\n\n"
        
        # Whisper configuration
        env_content += "# Whisper.cpp Configuration\n"
        for key, value in env_vars.items():
            env_content += f"{key}={value}\n"
        
        # Django optimizations
        env_content += "\n# Django Configuration\n"
        django_opts = optimizations['django']
        for key, value in django_opts.items():
            env_content += f"{key}={value}\n"
        
        # Redis configuration
        env_content += "\n# Redis Configuration\n"
        redis_opts = optimizations['redis']
        env_content += f"REDIS_MAXMEMORY={redis_opts['maxmemory']}\n"
        env_content += f"REDIS_MAXMEMORY_POLICY={redis_opts['maxmemory_policy']}\n"
        
        with open(f"{output_dir}/cupcake.env", 'w') as f:
            f.write(env_content)
        
        # System information JSON
        system_data = {
            'system_info': self.system_info,
            'system_tier': self.get_system_tier(),
            'whisper_config': self.get_whisper_config(),
            'optimizations': optimizations,
            'generated_at': subprocess.check_output(['date', '-Iseconds']).decode().strip()
        }
        
        with open(f"{output_dir}/system-info.json", 'w') as f:
            json.dump(system_data, f, indent=2)
        
        return output_dir
    
    def print_recommendations(self):
        """Print human-readable system recommendations"""
        tier = self.get_system_tier()
        whisper_config = self.get_whisper_config()
        optimizations = self.get_system_optimizations()
        
        print("=== CUPCAKE System Capability Analysis ===")
        print(f"System: {self.system_info['pi_model'] or platform.platform()}")
        print(f"Memory: {self.system_info['total_memory_mb']} MB")
        print(f"CPU Cores: {self.system_info['cpu_count']} logical, {self.system_info['cpu_count_physical']} physical")
        print(f"Performance Tier: {tier.upper()}")
        print()
        
        print("=== Whisper.cpp Recommendations ===")
        print(f"Recommended Model: {whisper_config['model']}")
        print(f"Thread Count: {whisper_config['thread_count']}")
        print(f"Description: {whisper_config['description']}")
        print(f"Models to Download: {', '.join(whisper_config['recommended_models'])}")
        print()
        
        print("=== System Optimizations ===")
        pg_opts = optimizations['postgresql']
        print(f"PostgreSQL shared_buffers: {pg_opts['shared_buffers']}")
        print(f"PostgreSQL work_mem: {pg_opts['work_mem']}")
        print(f"Redis max memory: {optimizations['redis']['maxmemory']}")
        
        django_opts = optimizations['django']
        print(f"Enable LLM features: {django_opts['USE_LLM']}")
        print(f"RQ timeout: {django_opts['RQ_DEFAULT_TIMEOUT']}s")
        print()


def main():
    """Main entry point"""
    detector = SystemCapabilityDetector()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'json':
            # Output JSON format
            system_data = {
                'system_info': detector.system_info,
                'system_tier': detector.get_system_tier(),
                'whisper_config': detector.get_whisper_config(),
                'django_env_vars': detector.get_django_env_vars(),
                'optimizations': detector.get_system_optimizations()
            }
            print(json.dumps(system_data, indent=2))
            
        elif command == 'env':
            # Output environment variables
            env_vars = detector.get_django_env_vars()
            for key, value in env_vars.items():
                print(f"export {key}={value}")
                
        elif command == 'whisper':
            # Output just Whisper config
            whisper_config = detector.get_whisper_config()
            print(json.dumps(whisper_config, indent=2))
            
        elif command == 'tier':
            # Output just the performance tier
            print(detector.get_system_tier())
            
        elif command == 'generate':
            # Generate configuration files
            output_dir = sys.argv[2] if len(sys.argv) > 2 else "/opt/cupcake/config"
            config_dir = detector.generate_config_files(output_dir)
            print(f"Configuration files generated in: {config_dir}")
            
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    else:
        # Default: print recommendations
        detector.print_recommendations()


if __name__ == '__main__':
    main()
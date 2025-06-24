import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from django.conf import settings

@pytest.fixture(scope="session", autouse=True)
def test_containers():
    with PostgresContainer("postgres:14") as postgres, RedisContainer("redis:latest") as redis:
        settings.DATABASES["default"].update({
            "ENGINE": "django.db.backends.postgresql",
            "NAME": postgres.DBNAME,
            "USER": postgres.USER,
            "PASSWORD": postgres.PASSWORD,
            "HOST": postgres.get_container_host_ip(),
            "PORT": postgres.get_exposed_port(5432),
        })
        settings.CACHES["default"].update({
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/1",
        })
        yield
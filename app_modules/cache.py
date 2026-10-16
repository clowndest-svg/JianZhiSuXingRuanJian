"""Bounded Redis connections; callers retain their explicit memory fallback."""
import os
import redis

client=redis.Redis(host=os.environ.get('QINGSU_REDIS_HOST','127.0.0.1'),port=int(os.environ.get('QINGSU_REDIS_PORT','6379')),
                   socket_connect_timeout=.35,socket_timeout=.35,decode_responses=True,max_connections=16)

def command(args):
    namespace=os.environ.get('QINGSU_CACHE_NAMESPACE','qingsu-prod')
    if not namespace.replace('-','').replace('_','').isalnum():raise ValueError('Invalid cache namespace')
    # Namespace only application keys, including the key argument of EVAL.
    args=[namespace+':'+v[3:] if isinstance(v,str) and v.startswith('qs:') else v for v in args]
    return client.execute_command(*args)

LIMIT_SCRIPT="local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]); end; return n"

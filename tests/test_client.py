import asyncio
import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from research_lab.recorder import MarketDataClient, load_signer


def test_signer_uses_documented_path_and_digest_salt(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv('KALSHI_API_KEY_ID', 'test-key')
    monkeypatch.setenv('KALSHI_PRIVATE_KEY_PEM', pem)
    headers = load_signer()()
    assert headers['KALSHI-ACCESS-KEY'] == 'test-key'
    message = (headers['KALSHI-ACCESS-TIMESTAMP'] + 'GET/trade-api/ws/v2').encode()
    key.public_key().verify(base64.b64decode(headers['KALSHI-ACCESS-SIGNATURE']), message,
                            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())


def test_client_rejects_account_and_order_paths_without_request():
    async def check():
        client = MarketDataClient()
        try:
            for path in ('/portfolio/orders', '/account', 'https://example.com'):
                with pytest.raises(ValueError, match='market-data'):
                    await client.get(path)
            assert not hasattr(client, 'post')
        finally:
            await client.close()
    asyncio.run(check())

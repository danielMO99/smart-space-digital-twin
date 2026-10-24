from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_frontend_and_existing_routes():
    with TestClient(create_app()) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert 'id="floor"' in page.text
        for path in ('css/styles.css', 'js/app.js', 'js/geometry.mjs'):
            response = client.get('/static/' + path)
            assert response.status_code == 200
            if path.endswith(('.js', '.mjs')):
                assert 'javascript' in response.headers['content-type']
        assert client.get('/health').status_code == 200
        assert client.get('/api/room').json()['room']['width_m'] == 4
        assert client.get('/api/state').status_code == 200
        assert client.get('/docs').status_code == 200
        assert client.get('/static/../config/room.json').status_code == 404
        with client.websocket_connect('/ws') as ws:
            assert len(ws.receive_json()['targets']) == 3

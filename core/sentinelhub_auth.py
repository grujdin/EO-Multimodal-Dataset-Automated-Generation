from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session

CLIENT_ID = "edc00d-7ecb-4baf-8e3bbb56764"
CLIENT_SECRET = "9OgD9zMKQtWrdfdfdfdIgFTKBoyiuEI"

def get_sentinelhub_token(client_id=CLIENT_ID, client_secret=CLIENT_SECRET):
    try:
        client = BackendApplicationClient(client_id=client_id)
        oauth = OAuth2Session(client=client)
        token = oauth.fetch_token(
            token_url='https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token',
            client_id=client_id,
            client_secret=client_secret,
            include_client_id=True
        )
        return token.get("access_token")
    except Exception as e:
        import traceback
        print("OAuth2 Error:", e)
        traceback.print_exc()
        return None

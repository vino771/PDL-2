import firebase_admin
from firebase_admin import credentials
from firebase_admin import db


cred = credentials.Certificate(
    "serviceAccountKey.json"
)


firebase_admin.initialize_app(
    cred,
    {
        "databaseURL":
        "https://floating-solar-panel-default-rtdb.asia-southeast1.firebasedatabase.app/"
    }
)


def get_data():

    ref = db.reference(
        "/floatingSolarPanel"
    )

    data = ref.get()

    return data
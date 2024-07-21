from motor.motor_asyncio import AsyncIOMotorClient

MONGO_DETAILS = "mongodb+srv://sco3o17:1q2w3e4r@cluster0.al5hilk.mongodb.net/"

client = AsyncIOMotorClient(MONGO_DETAILS)

db = client.imadyou

userCollection = db.get_collection("user")
projectCollection = db.get_collection("project")
statusCollection = db.get_collection("status")
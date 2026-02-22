import json
import os

class Database:
    def __init__(self, file_path="reviews.json"):
        self.file_path = file_path
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump({"last_id": 0, "reviews": []}, f)

    def _read(self):
        with open(self.file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write(self, data):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def add_review(self, user_id, content, photos, label, rating):
        data = self._read()
        data["last_id"] += 1
        new_id = data["last_id"]
        
        review = {
            "id": new_id,
            "user_id": user_id,
            "content": content,
            "photos": photos,
            "label": label,
            "rating": rating,
            "status": "pending"
        }
        data["reviews"].append(review)
        self._write(data)
        return new_id

    def get_review(self, review_id):
        data = self._read()
        for r in data["reviews"]:
            if r["id"] == review_id:
                return r
        return None

    def update_status(self, review_id, status):
        data = self._read()
        for r in data["reviews"]:
            if r["id"] == review_id:
                r["status"] = status
                break
        self._write(data)
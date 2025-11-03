import uuid
from typing import Dict, List, Any

# This will be a singleton-like in-memory store.
# The key is a unique board_id (UUID string).
# The value is a dictionary containing the name and the list of findings.
MEMORY_BOARDS: Dict[str, Dict[str, Any]] = {}

class MemoryService:
    """
    Manages in-memory "memory boards" for AI-led investigations.
    Each board has a unique ID, a name, and a list of findings.
    """

    def create_board(self, name: str) -> Dict[str, str]:
        """Creates a new memory board and returns its unique ID and name."""
        board_id = str(uuid.uuid4())
        MEMORY_BOARDS[board_id] = {
            "name": name,
            "findings": []
        }
        return {"board_id": board_id, "name": name}

    def add_finding(self, board_id: str, finding_data: Dict[str, Any]) -> Dict[str, str]:
        """Adds a finding to a specific memory board."""
        if board_id in MEMORY_BOARDS:
            MEMORY_BOARDS[board_id]["findings"].append(finding_data)
            # Optional: sort findings chronologically if they have a timestamp
            findings = MEMORY_BOARDS[board_id]["findings"]
            if findings and "timestamp" in findings[-1]:
                 findings.sort(key=lambda x: x.get("timestamp", ""))
            return {"status": "success"}
        return {"status": "error", "message": "Memory board not found"}

    def get_board(self, board_id: str) -> Dict[str, Any]:
        """Retrievels an entire memory board."""
        return MEMORY_BOARDS.get(board_id, {})

    def clear_board(self, board_id: str) -> Dict[str, str]:
        """Clears a specific memory board from memory."""
        if board_id in MEMORY_BOARDS:
            del MEMORY_BOARDS[board_id]
            return {"status": "cleared"}
        return {"status": "not_found"}

    def list_all_boards(self) -> List[Dict[str, str]]:
        """
        Returns a lightweight summary list (ID and name) of all active memory boards.
        """
        summary_list = [
            {
                "board_id": board_id,
                "name": board_data["name"]
            }
            for board_id, board_data in MEMORY_BOARDS.items()
        ]
        return summary_list

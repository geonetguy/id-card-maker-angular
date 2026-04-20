# MIGRATION RULES

This repo is a controlled migration from Toga → Angular.

Do NOT:
- Rewrite rendering logic
- Change data formats
- Modify business rules

Do:
- Extract APIs from existing logic
- Replace UI only
- Maintain behavior parity
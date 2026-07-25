"""
Domain-Agnostic Protected Attribute Registry & Dynamic Baseline Mapper
"""

import random
import pandas as pd
from typing import Dict, Any, List

DOMAIN_AGNOSTIC_REGISTRY = [
    # Sovereign / Geography
    {"attribute_type": "country", "value": "India", "is_protected": True, "justified_offset": 0.0100},
    {"attribute_type": "country", "value": "Brazil", "is_protected": True, "justified_offset": 0.0125},
    {"attribute_type": "country", "value": "South_Africa", "is_protected": True, "justified_offset": 0.0150},
    {"attribute_type": "country", "value": "US_Delaware", "is_protected": False, "justified_offset": 0.0000},
    {"attribute_type": "country", "value": "UK_London", "is_protected": False, "justified_offset": 0.0000},
    
    # Zip Codes / Regions
    {"attribute_type": "zip_code", "value": "48201_Detroit_MI", "is_protected": True, "justified_offset": 0.0000},
    {"attribute_type": "zip_code", "value": "60621_Chicago_IL", "is_protected": True, "justified_offset": 0.0000},
    {"attribute_type": "zip_code", "value": "10001_NewYork_NY", "is_protected": False, "justified_offset": 0.0000},
    {"attribute_type": "zip_code", "value": "90210_BeverlyHills_CA", "is_protected": False, "justified_offset": 0.0000},
    
    # Gender
    {"attribute_type": "gender", "value": "Female", "is_protected": True, "justified_offset": 0.0000},
    {"attribute_type": "gender", "value": "Non-Binary", "is_protected": True, "justified_offset": 0.0000},
    {"attribute_type": "gender", "value": "Male", "is_protected": False, "justified_offset": 0.0000},
    
    # Age Groups
    {"attribute_type": "age_group", "value": "Senior_65Plus", "is_protected": True, "justified_offset": 0.0000},
    {"attribute_type": "age_group", "value": "Young_Under25", "is_protected": True, "justified_offset": 0.0000},
    {"attribute_type": "age_group", "value": "Mid_30s", "is_protected": False, "justified_offset": 0.0000},

    # Demographic Tiers
    {"attribute_type": "group_attribute", "value": "CRA_Tier_3_LowIncome", "is_protected": True, "justified_offset": 0.0000},
    {"attribute_type": "group_attribute", "value": "CRA_Tier_1_Baseline", "is_protected": False, "justified_offset": 0.0000},
]

class ProtectedAttributeRegistry:
    def __init__(self):
        self.df = pd.DataFrame(DOMAIN_AGNOSTIC_REGISTRY)

    def is_value_protected(self, attribute_type: str, value: str) -> bool:
        """Case-insensitive, stripped lookup."""
        clean_type = str(attribute_type).strip().lower()
        clean_val = str(value).strip().lower()
        
        matches = self.df[
            (self.df["attribute_type"].str.lower() == clean_type) & 
            (self.df["value"].str.lower() == clean_val)
        ]
        return not matches.empty and bool(matches.iloc[0]["is_protected"])

    def get_justified_offset(self, attribute_type: str, value: str) -> float:
        """Returns justified offset evaluated to 4 decimal places."""
        clean_type = str(attribute_type).strip().lower()
        clean_val = str(value).strip().lower()
        
        matches = self.df[
            (self.df["attribute_type"].str.lower() == clean_type) & 
            (self.df["value"].str.lower() == clean_val)
        ]
        if not matches.empty:
            return round(float(matches.iloc[0]["justified_offset"]), 4)
        return 0.0000

    def sample_random_non_protected_baseline(self, attribute_type: str) -> str:
        """Randomly selects a non-protected (Is_Protected = False) baseline."""
        clean_type = str(attribute_type).strip().lower()
        baselines = self.df[
            (self.df["attribute_type"].str.lower() == clean_type) & 
            (self.df["is_protected"] == False)
        ]
        if not baselines.empty:
            return str(random.choice(baselines["value"].tolist()))
        return "Baseline_Reference"
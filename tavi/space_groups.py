"""Space group data and extinction rules for crystallography.

This module provides the 230 crystallographic space groups with their
properties and extinction (systematic absence) rules based on Bravais lattice
centering.

Reference: International Tables for Crystallography, Volume A
"""
from dataclasses import dataclass
from typing import Optional, List, Tuple


@dataclass(frozen=True)
class SpaceGroup:
    """Represents a crystallographic space group."""
    number: int              # International space group number (1-230)
    short_name: str          # Short Hermann-Mauguin symbol (e.g., "Fm-3m")
    crystal_system: str      # One of: triclinic, monoclinic, orthorhombic, tetragonal, trigonal, hexagonal, cubic
    centering: str           # Bravais lattice centering: P, I, F, C, A, B, R
    
    @property
    def display_name(self) -> str:
        """Return formatted display name for UI."""
        return f"{self.number} - {self.short_name} ({self.crystal_system.capitalize()})"
    
    @property
    def search_text(self) -> str:
        """Return text for searching."""
        return f"{self.number} {self.short_name} {self.crystal_system}".lower()


# Crystal system definitions with lattice constraints
CRYSTAL_SYSTEMS = {
    "triclinic": {
        "constraints": "a ≠ b ≠ c, α ≠ β ≠ γ",
        "sg_range": (1, 2),
    },
    "monoclinic": {
        "constraints": "a ≠ b ≠ c, α = γ = 90°, β ≠ 90°",
        "sg_range": (3, 15),
    },
    "orthorhombic": {
        "constraints": "a ≠ b ≠ c, α = β = γ = 90°",
        "sg_range": (16, 74),
    },
    "tetragonal": {
        "constraints": "a = b ≠ c, α = β = γ = 90°",
        "sg_range": (75, 142),
    },
    "trigonal": {
        "constraints": "a = b ≠ c, α = β = 90°, γ = 120° (hex) or a = b = c, α = β = γ (rhomb)",
        "sg_range": (143, 167),
    },
    "hexagonal": {
        "constraints": "a = b ≠ c, α = β = 90°, γ = 120°",
        "sg_range": (168, 194),
    },
    "cubic": {
        "constraints": "a = b = c, α = β = γ = 90°",
        "sg_range": (195, 230),
    },
}


# Extinction rules based on Bravais lattice centering
# These are the systematic absence conditions for each centering type
EXTINCTION_RULES = {
    "P": {
        "name": "Primitive",
        "forbidden": "None (all reflections allowed)",
        "allowed": "Any h, k, l",
        "rule_func": lambda h, k, l: True,  # All allowed
    },
    "I": {
        "name": "Body-centered",
        "forbidden": "h + k + l = odd",
        "allowed": "h + k + l = even",
        "rule_func": lambda h, k, l: (h + k + l) % 2 == 0,
    },
    "F": {
        "name": "Face-centered",
        "forbidden": "h, k, l mixed (some odd, some even)",
        "allowed": "h, k, l all odd OR all even",
        "rule_func": lambda h, k, l: (h % 2 == k % 2 == l % 2),
    },
    "C": {
        "name": "C-centered (base-centered on ab face)",
        "forbidden": "h + k = odd",
        "allowed": "h + k = even",
        "rule_func": lambda h, k, l: (h + k) % 2 == 0,
    },
    "A": {
        "name": "A-centered (base-centered on bc face)",
        "forbidden": "k + l = odd",
        "allowed": "k + l = even",
        "rule_func": lambda h, k, l: (k + l) % 2 == 0,
    },
    "B": {
        "name": "B-centered (base-centered on ac face)",
        "forbidden": "h + l = odd",
        "allowed": "h + l = even",
        "rule_func": lambda h, k, l: (h + l) % 2 == 0,
    },
    "R": {
        "name": "Rhombohedral (hexagonal axes)",
        "forbidden": "-h + k + l ≠ 3n",
        "allowed": "-h + k + l = 3n (n integer)",
        "rule_func": lambda h, k, l: (-h + k + l) % 3 == 0,
    },
}


def is_reflection_allowed(h: int, k: int, l: int, centering: str) -> bool:
    """Check if a reflection (h, k, l) is allowed for the given centering type.
    
    Args:
        h, k, l: Miller indices
        centering: Bravais lattice centering type (P, I, F, C, A, B, R)
        
    Returns:
        True if reflection is allowed, False if systematically absent
    """
    if centering not in EXTINCTION_RULES:
        return True  # Default to allowed if unknown centering
    return EXTINCTION_RULES[centering]["rule_func"](h, k, l)


def get_extinction_rule_text(centering: str) -> Tuple[str, str, str]:
    """Get human-readable extinction rule text for a centering type.
    
    Args:
        centering: Bravais lattice centering type
        
    Returns:
        Tuple of (centering_name, forbidden_text, allowed_text)
    """
    if centering not in EXTINCTION_RULES:
        return ("Unknown", "Unknown", "Unknown")
    rule = EXTINCTION_RULES[centering]
    return (rule["name"], rule["forbidden"], rule["allowed"])


def get_crystal_system(sg_number: int) -> str:
    """Get the crystal system for a space group number."""
    for system, info in CRYSTAL_SYSTEMS.items():
        low, high = info["sg_range"]
        if low <= sg_number <= high:
            return system
    return "unknown"


def get_centering_from_symbol(short_name: str) -> str:
    """Extract the centering letter from a space group symbol."""
    if not short_name:
        return "P"
    first_char = short_name[0].upper()
    if first_char in ("P", "I", "F", "C", "A", "B", "R"):
        return first_char
    return "P"


# Complete list of 230 space groups
# Format: (number, short_name, crystal_system, centering)
# Data derived from International Tables for Crystallography
SPACE_GROUPS_DATA = [
    # Triclinic (1-2)
    (1, "P1", "triclinic", "P"),
    (2, "P-1", "triclinic", "P"),
    
    # Monoclinic (3-15)
    (3, "P2", "monoclinic", "P"),
    (4, "P2₁", "monoclinic", "P"),
    (5, "C2", "monoclinic", "C"),
    (6, "Pm", "monoclinic", "P"),
    (7, "Pc", "monoclinic", "P"),
    (8, "Cm", "monoclinic", "C"),
    (9, "Cc", "monoclinic", "C"),
    (10, "P2/m", "monoclinic", "P"),
    (11, "P2₁/m", "monoclinic", "P"),
    (12, "C2/m", "monoclinic", "C"),
    (13, "P2/c", "monoclinic", "P"),
    (14, "P2₁/c", "monoclinic", "P"),
    (15, "C2/c", "monoclinic", "C"),
    
    # Orthorhombic (16-74)
    (16, "P222", "orthorhombic", "P"),
    (17, "P222₁", "orthorhombic", "P"),
    (18, "P2₁2₁2", "orthorhombic", "P"),
    (19, "P2₁2₁2₁", "orthorhombic", "P"),
    (20, "C222₁", "orthorhombic", "C"),
    (21, "C222", "orthorhombic", "C"),
    (22, "F222", "orthorhombic", "F"),
    (23, "I222", "orthorhombic", "I"),
    (24, "I2₁2₁2₁", "orthorhombic", "I"),
    (25, "Pmm2", "orthorhombic", "P"),
    (26, "Pmc2₁", "orthorhombic", "P"),
    (27, "Pcc2", "orthorhombic", "P"),
    (28, "Pma2", "orthorhombic", "P"),
    (29, "Pca2₁", "orthorhombic", "P"),
    (30, "Pnc2", "orthorhombic", "P"),
    (31, "Pmn2₁", "orthorhombic", "P"),
    (32, "Pba2", "orthorhombic", "P"),
    (33, "Pna2₁", "orthorhombic", "P"),
    (34, "Pnn2", "orthorhombic", "P"),
    (35, "Cmm2", "orthorhombic", "C"),
    (36, "Cmc2₁", "orthorhombic", "C"),
    (37, "Ccc2", "orthorhombic", "C"),
    (38, "Amm2", "orthorhombic", "A"),
    (39, "Aem2", "orthorhombic", "A"),
    (40, "Ama2", "orthorhombic", "A"),
    (41, "Aea2", "orthorhombic", "A"),
    (42, "Fmm2", "orthorhombic", "F"),
    (43, "Fdd2", "orthorhombic", "F"),
    (44, "Imm2", "orthorhombic", "I"),
    (45, "Iba2", "orthorhombic", "I"),
    (46, "Ima2", "orthorhombic", "I"),
    (47, "Pmmm", "orthorhombic", "P"),
    (48, "Pnnn", "orthorhombic", "P"),
    (49, "Pccm", "orthorhombic", "P"),
    (50, "Pban", "orthorhombic", "P"),
    (51, "Pmma", "orthorhombic", "P"),
    (52, "Pnna", "orthorhombic", "P"),
    (53, "Pmna", "orthorhombic", "P"),
    (54, "Pcca", "orthorhombic", "P"),
    (55, "Pbam", "orthorhombic", "P"),
    (56, "Pccn", "orthorhombic", "P"),
    (57, "Pbcm", "orthorhombic", "P"),
    (58, "Pnnm", "orthorhombic", "P"),
    (59, "Pmmn", "orthorhombic", "P"),
    (60, "Pbcn", "orthorhombic", "P"),
    (61, "Pbca", "orthorhombic", "P"),
    (62, "Pnma", "orthorhombic", "P"),
    (63, "Cmcm", "orthorhombic", "C"),
    (64, "Cmce", "orthorhombic", "C"),
    (65, "Cmmm", "orthorhombic", "C"),
    (66, "Cccm", "orthorhombic", "C"),
    (67, "Cmme", "orthorhombic", "C"),
    (68, "Ccce", "orthorhombic", "C"),
    (69, "Fmmm", "orthorhombic", "F"),
    (70, "Fddd", "orthorhombic", "F"),
    (71, "Immm", "orthorhombic", "I"),
    (72, "Ibam", "orthorhombic", "I"),
    (73, "Ibca", "orthorhombic", "I"),
    (74, "Imma", "orthorhombic", "I"),
    
    # Tetragonal (75-142)
    (75, "P4", "tetragonal", "P"),
    (76, "P4₁", "tetragonal", "P"),
    (77, "P4₂", "tetragonal", "P"),
    (78, "P4₃", "tetragonal", "P"),
    (79, "I4", "tetragonal", "I"),
    (80, "I4₁", "tetragonal", "I"),
    (81, "P-4", "tetragonal", "P"),
    (82, "I-4", "tetragonal", "I"),
    (83, "P4/m", "tetragonal", "P"),
    (84, "P4₂/m", "tetragonal", "P"),
    (85, "P4/n", "tetragonal", "P"),
    (86, "P4₂/n", "tetragonal", "P"),
    (87, "I4/m", "tetragonal", "I"),
    (88, "I4₁/a", "tetragonal", "I"),
    (89, "P422", "tetragonal", "P"),
    (90, "P42₁2", "tetragonal", "P"),
    (91, "P4₁22", "tetragonal", "P"),
    (92, "P4₁2₁2", "tetragonal", "P"),
    (93, "P4₂22", "tetragonal", "P"),
    (94, "P4₂2₁2", "tetragonal", "P"),
    (95, "P4₃22", "tetragonal", "P"),
    (96, "P4₃2₁2", "tetragonal", "P"),
    (97, "I422", "tetragonal", "I"),
    (98, "I4₁22", "tetragonal", "I"),
    (99, "P4mm", "tetragonal", "P"),
    (100, "P4bm", "tetragonal", "P"),
    (101, "P4₂cm", "tetragonal", "P"),
    (102, "P4₂nm", "tetragonal", "P"),
    (103, "P4cc", "tetragonal", "P"),
    (104, "P4nc", "tetragonal", "P"),
    (105, "P4₂mc", "tetragonal", "P"),
    (106, "P4₂bc", "tetragonal", "P"),
    (107, "I4mm", "tetragonal", "I"),
    (108, "I4cm", "tetragonal", "I"),
    (109, "I4₁md", "tetragonal", "I"),
    (110, "I4₁cd", "tetragonal", "I"),
    (111, "P-42m", "tetragonal", "P"),
    (112, "P-42c", "tetragonal", "P"),
    (113, "P-42₁m", "tetragonal", "P"),
    (114, "P-42₁c", "tetragonal", "P"),
    (115, "P-4m2", "tetragonal", "P"),
    (116, "P-4c2", "tetragonal", "P"),
    (117, "P-4b2", "tetragonal", "P"),
    (118, "P-4n2", "tetragonal", "P"),
    (119, "I-4m2", "tetragonal", "I"),
    (120, "I-4c2", "tetragonal", "I"),
    (121, "I-42m", "tetragonal", "I"),
    (122, "I-42d", "tetragonal", "I"),
    (123, "P4/mmm", "tetragonal", "P"),
    (124, "P4/mcc", "tetragonal", "P"),
    (125, "P4/nbm", "tetragonal", "P"),
    (126, "P4/nnc", "tetragonal", "P"),
    (127, "P4/mbm", "tetragonal", "P"),
    (128, "P4/mnc", "tetragonal", "P"),
    (129, "P4/nmm", "tetragonal", "P"),
    (130, "P4/ncc", "tetragonal", "P"),
    (131, "P4₂/mmc", "tetragonal", "P"),
    (132, "P4₂/mcm", "tetragonal", "P"),
    (133, "P4₂/nbc", "tetragonal", "P"),
    (134, "P4₂/nnm", "tetragonal", "P"),
    (135, "P4₂/mbc", "tetragonal", "P"),
    (136, "P4₂/mnm", "tetragonal", "P"),
    (137, "P4₂/nmc", "tetragonal", "P"),
    (138, "P4₂/ncm", "tetragonal", "P"),
    (139, "I4/mmm", "tetragonal", "I"),
    (140, "I4/mcm", "tetragonal", "I"),
    (141, "I4₁/amd", "tetragonal", "I"),
    (142, "I4₁/acd", "tetragonal", "I"),
    
    # Trigonal (143-167)
    (143, "P3", "trigonal", "P"),
    (144, "P3₁", "trigonal", "P"),
    (145, "P3₂", "trigonal", "P"),
    (146, "R3", "trigonal", "R"),
    (147, "P-3", "trigonal", "P"),
    (148, "R-3", "trigonal", "R"),
    (149, "P312", "trigonal", "P"),
    (150, "P321", "trigonal", "P"),
    (151, "P3₁12", "trigonal", "P"),
    (152, "P3₁21", "trigonal", "P"),
    (153, "P3₂12", "trigonal", "P"),
    (154, "P3₂21", "trigonal", "P"),
    (155, "R32", "trigonal", "R"),
    (156, "P3m1", "trigonal", "P"),
    (157, "P31m", "trigonal", "P"),
    (158, "P3c1", "trigonal", "P"),
    (159, "P31c", "trigonal", "P"),
    (160, "R3m", "trigonal", "R"),
    (161, "R3c", "trigonal", "R"),
    (162, "P-31m", "trigonal", "P"),
    (163, "P-31c", "trigonal", "P"),
    (164, "P-3m1", "trigonal", "P"),
    (165, "P-3c1", "trigonal", "P"),
    (166, "R-3m", "trigonal", "R"),
    (167, "R-3c", "trigonal", "R"),
    
    # Hexagonal (168-194)
    (168, "P6", "hexagonal", "P"),
    (169, "P6₁", "hexagonal", "P"),
    (170, "P6₅", "hexagonal", "P"),
    (171, "P6₂", "hexagonal", "P"),
    (172, "P6₄", "hexagonal", "P"),
    (173, "P6₃", "hexagonal", "P"),
    (174, "P-6", "hexagonal", "P"),
    (175, "P6/m", "hexagonal", "P"),
    (176, "P6₃/m", "hexagonal", "P"),
    (177, "P622", "hexagonal", "P"),
    (178, "P6₁22", "hexagonal", "P"),
    (179, "P6₅22", "hexagonal", "P"),
    (180, "P6₂22", "hexagonal", "P"),
    (181, "P6₄22", "hexagonal", "P"),
    (182, "P6₃22", "hexagonal", "P"),
    (183, "P6mm", "hexagonal", "P"),
    (184, "P6cc", "hexagonal", "P"),
    (185, "P6₃cm", "hexagonal", "P"),
    (186, "P6₃mc", "hexagonal", "P"),
    (187, "P-6m2", "hexagonal", "P"),
    (188, "P-6c2", "hexagonal", "P"),
    (189, "P-62m", "hexagonal", "P"),
    (190, "P-62c", "hexagonal", "P"),
    (191, "P6/mmm", "hexagonal", "P"),
    (192, "P6/mcc", "hexagonal", "P"),
    (193, "P6₃/mcm", "hexagonal", "P"),
    (194, "P6₃/mmc", "hexagonal", "P"),
    
    # Cubic (195-230)
    (195, "P23", "cubic", "P"),
    (196, "F23", "cubic", "F"),
    (197, "I23", "cubic", "I"),
    (198, "P2₁3", "cubic", "P"),
    (199, "I2₁3", "cubic", "I"),
    (200, "Pm-3", "cubic", "P"),
    (201, "Pn-3", "cubic", "P"),
    (202, "Fm-3", "cubic", "F"),
    (203, "Fd-3", "cubic", "F"),
    (204, "Im-3", "cubic", "I"),
    (205, "Pa-3", "cubic", "P"),
    (206, "Ia-3", "cubic", "I"),
    (207, "P432", "cubic", "P"),
    (208, "P4₂32", "cubic", "P"),
    (209, "F432", "cubic", "F"),
    (210, "F4₁32", "cubic", "F"),
    (211, "I432", "cubic", "I"),
    (212, "P4₃32", "cubic", "P"),
    (213, "P4₁32", "cubic", "P"),
    (214, "I4₁32", "cubic", "I"),
    (215, "P-43m", "cubic", "P"),
    (216, "F-43m", "cubic", "F"),
    (217, "I-43m", "cubic", "I"),
    (218, "P-43n", "cubic", "P"),
    (219, "F-43c", "cubic", "F"),
    (220, "I-43d", "cubic", "I"),
    (221, "Pm-3m", "cubic", "P"),
    (222, "Pn-3n", "cubic", "P"),
    (223, "Pm-3n", "cubic", "P"),
    (224, "Pn-3m", "cubic", "P"),
    (225, "Fm-3m", "cubic", "F"),
    (226, "Fm-3c", "cubic", "F"),
    (227, "Fd-3m", "cubic", "F"),
    (228, "Fd-3c", "cubic", "F"),
    (229, "Im-3m", "cubic", "I"),
    (230, "Ia-3d", "cubic", "I"),
]

# Build SpaceGroup objects from data
SPACE_GROUPS: List[SpaceGroup] = [
    SpaceGroup(number=num, short_name=name, crystal_system=system, centering=cent)
    for num, name, system, cent in SPACE_GROUPS_DATA
]

# Create lookup dictionaries for fast access
SPACE_GROUPS_BY_NUMBER = {sg.number: sg for sg in SPACE_GROUPS}
SPACE_GROUPS_BY_NAME = {sg.short_name.lower(): sg for sg in SPACE_GROUPS}


def get_space_group(identifier) -> Optional[SpaceGroup]:
    """Get a space group by number or name.
    
    Args:
        identifier: Space group number (int) or short name (str)
        
    Returns:
        SpaceGroup object or None if not found
    """
    if isinstance(identifier, int):
        return SPACE_GROUPS_BY_NUMBER.get(identifier)
    elif isinstance(identifier, str):
        # Try exact match first
        sg = SPACE_GROUPS_BY_NAME.get(identifier.lower())
        if sg:
            return sg
        # Try matching by number at start
        try:
            num = int(identifier.split()[0].split("-")[0])
            return SPACE_GROUPS_BY_NUMBER.get(num)
        except (ValueError, IndexError):
            pass
    return None


def search_space_groups(query: str, limit: int = 20) -> List[SpaceGroup]:
    """Search for space groups matching a query string.
    
    Args:
        query: Search query (matches number, name, or crystal system)
        limit: Maximum number of results
        
    Returns:
        List of matching SpaceGroup objects
    """
    if not query:
        return SPACE_GROUPS[:limit]
    
    query_lower = query.lower().strip()
    results = []
    
    # Try exact number match first
    try:
        num = int(query_lower)
        if 1 <= num <= 230:
            sg = SPACE_GROUPS_BY_NUMBER.get(num)
            if sg:
                results.append(sg)
    except ValueError:
        pass
    
    # Then search by name and system
    for sg in SPACE_GROUPS:
        if sg in results:
            continue
        if query_lower in sg.search_text:
            results.append(sg)
            if len(results) >= limit:
                break
    
    return results


def filter_by_crystal_system(system: str) -> List[SpaceGroup]:
    """Get all space groups for a given crystal system.
    
    Args:
        system: Crystal system name
        
    Returns:
        List of SpaceGroup objects
    """
    system_lower = system.lower()
    return [sg for sg in SPACE_GROUPS if sg.crystal_system == system_lower]


def generate_allowed_reflections(centering: str, h_max: int = 5, k_max: int = 5, l_max: int = 5) -> List[Tuple[int, int, int]]:
    """Generate a list of allowed (h, k, l) reflections up to given limits.
    
    Args:
        centering: Bravais lattice centering type
        h_max, k_max, l_max: Maximum absolute values for indices
        
    Returns:
        List of (h, k, l) tuples for allowed reflections
    """
    allowed = []
    for h in range(-h_max, h_max + 1):
        for k in range(-k_max, k_max + 1):
            for l in range(-l_max, l_max + 1):
                if h == 0 and k == 0 and l == 0:
                    continue  # Skip (0, 0, 0)
                if is_reflection_allowed(h, k, l, centering):
                    allowed.append((h, k, l))
    return allowed

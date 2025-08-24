"""
SDRF-Proteomics default values structured data for providing default options in SDRF metadata forms.
"""

# Single-value required fields
REQUIRED_SINGLE_VALUES = {"technology type": ["proteomic profiling by mass spectrometry"]}

# Label values
LABEL_VALUES = {
    "label free sample": ["label free sample"],
    "tmt_labels": [
        "TMT126",
        "TMT127",
        "TMT127C",
        "TMT127N",
        "TMT128",
        "TMT128C",
        "TMT128N",
        "TMT129",
        "TMT129C",
        "TMT129N",
        "TMT130",
        "TMT130C",
        "TMT130N",
        "TMT131",
    ],
    "silac_labels": ["SILAC light", "SILAC medium", "SILAC heavy"],
}

# Instrument models
INSTRUMENT_MODELS = [
    "LTQ Orbitrap XL",
    "LTQ Orbitrap Velos",
    "Q Exactive",
    "Q Exactive Plus",
    "Q Exactive HF",
    "Q Exactive HF-X",
    "Orbitrap Fusion",
    "Orbitrap Fusion Lumos",
    "Orbitrap Eclipse",
    "TimsTOF Pro",
    "TripleTOF 5600",
    "TripleTOF 6600",
]

# Cleavage agents (structured as key-value pairs)
CLEAVAGE_AGENTS = {
    "enzymatic": [
        {"name": "Trypsin", "value": "NT=Trypsin;AC=MS:1001251"},
        {"name": "Lys-C", "value": "NT=Lys-C;AC=MS:1001309"},
        {"name": "Chymotrypsin", "value": "NT=Chymotrypsin;AC=MS:1001306"},
        {"name": "Pepsin", "value": "NT=Pepsin;AC=MS:1001313"},
        {"name": "Glu-C", "value": "NT=Glu-C;AC=MS:1001917"},
        {"name": "Asp-N", "value": "NT=Asp-N;AC=MS:1001304"},
        {"name": "Arg-C", "value": "NT=Arg-C;AC=MS:1001303"},
    ],
    "non_enzymatic": ["not applicable"],
}

# Protein modifications (structured for different types)
PROTEIN_MODIFICATIONS = {
    "fixed": [
        {"name": "Carbamidomethyl (C)", "value": "NT=Carbamidomethyl;AC=Unimod:4;MT=Fixed;PP=Anywhere;TA=C"},
        {"name": "TMT6plex (N-term)", "value": "NT=TMT6plex;AC=Unimod:737;MT=Fixed;PP=Any N-term;TA=*"},
        {"name": "TMT6plex (K)", "value": "NT=TMT6plex;AC=Unimod:737;MT=Fixed;PP=Anywhere;TA=K"},
    ],
    "variable": [
        {"name": "Oxidation (M)", "value": "NT=Oxidation;AC=Unimod:35;MT=Variable;PP=Anywhere;TA=M"},
        {"name": "Acetyl (N-term)", "value": "NT=Acetyl;AC=Unimod:1;MT=Variable;PP=Any N-term;TA=*"},
        {"name": "Deamidated (N,Q)", "value": "NT=Deamidated;AC=Unimod:7;MT=Variable;PP=Anywhere;TA=N,Q"},
        {"name": "Phospho (S,T,Y)", "value": "NT=Phospho;AC=Unimod:21;MT=Variable;PP=Anywhere;TA=S,T,Y"},
        {"name": "Gln->pyro-Glu (Q N-term)", "value": "NT=Gln->pyro-Glu;AC=Unimod:28;MT=Variable;PP=Any N-term;TA=Q"},
        {"name": "Glu->pyro-Glu (E N-term)", "value": "NT=Glu->pyro-Glu;AC=Unimod:27;MT=Variable;PP=Any N-term;TA=E"},
    ],
}

# Mass tolerances
MASS_TOLERANCES = {
    "precursor": ["5 ppm", "10 ppm", "20 ppm", "0.5 Da", "1 Da"],
    "fragment": ["0.01 Da", "0.02 Da", "0.5 Da", "0.6 Da", "20 ppm"],
}

# Fragmentation methods
FRAGMENTATION_METHODS = {
    "dissociation": ["HCD", "CID", "ETD", "EThcD"],
    "collision_energy": ["25 NCE", "30 NCE", "35 NCE", "27 eV", "30 eV"],
}

# Sample characteristics
SAMPLE_CHARACTERISTICS = {
    "organism": [
        "homo sapiens",
        "mus musculus",
        "rattus norvegicus",
        "saccharomyces cerevisiae",
        "escherichia coli",
        "arabidopsis thaliana",
    ],
    "disease": [
        "normal",
        "cancer",
        "diabetes mellitus",
        "alzheimer disease",
        "cardiovascular disease",
        "not applicable",
        "not available",
    ],
    "sex": ["male", "female", "not available", "not applicable"],
    "cell_type": [
        "epithelial cell",
        "fibroblast",
        "hepatocyte",
        "neuron",
        "macrophage",
        "T cell",
        "B cell",
        "not available",
        "not applicable",
    ],
}

# Sample preparation
SAMPLE_PREPARATION = {
    "enrichment_process": [
        "enrichment of phosphorylated protein",
        "enrichment of glycosylated protein",
        "no enrichment",
    ],
    "reduction_reagent": ["DTT", "TCEP", "beta-mercaptoethanol"],
    "alkylation_reagent": ["IAA", "IAM", "chloroacetamide"],
    "fractionation_method": [
        "off-gel electrophoresis",
        "high pH reversed-phase chromatography",
        "strong cation exchange chromatography",
        "no fractionation",
    ],
}

# Data acquisition methods
DATA_ACQUISITION_METHODS = [
    "data-dependent acquisition",
    "data-independent acquisition",
    "SWATH MS",
    "diaPASEF",
    "parallel reaction monitoring",
    "selected reaction monitoring",
]

# Special values
SPECIAL_VALUES = {
    "unknown_missing": ["not available", "not applicable"],
    "pooled_sample": ["not pooled", "pooled"],
    "synthetic_peptide": ["synthetic", "not synthetic"],
    "biological_replicate": ["1", "2", "3", "4", "5"],
    "technical_replicate": ["1", "2", "3", "4", "5"],
    "fraction_identifier": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
}

# Compound fields that require special handling
COMPOUND_FIELDS = {
    "comment[modification parameters]": {
        "format": "key_value_pairs",
        "separator": ";",
        "fields": {
            "NT": {"name": "Name", "required": True, "type": "text"},
            "AC": {"name": "Accession", "required": True, "type": "text"},
            "MT": {"name": "Modification Type", "required": True, "options": ["Fixed", "Variable"]},
            "PP": {
                "name": "Position",
                "required": True,
                "options": ["Anywhere", "Any N-term", "Any C-term", "Protein N-term", "Protein C-term"],
            },
            "TA": {
                "name": "Target Amino Acid",
                "required": True,
                "type": "text",
                "help": "Single letter amino acid codes, comma-separated",
            },
        },
        "examples": [
            "NT=Carbamidomethyl;AC=Unimod:4;MT=Fixed;PP=Anywhere;TA=C",
            "NT=Oxidation;AC=Unimod:35;MT=Variable;PP=Anywhere;TA=M",
        ],
    },
    "comment[cleavage agent details]": {
        "format": "key_value_pairs",
        "separator": ";",
        "fields": {
            "NT": {"name": "Name", "required": True, "type": "text"},
            "AC": {"name": "Accession", "required": True, "type": "text"},
        },
        "examples": ["NT=Trypsin;AC=MS:1001251", "NT=Lys-C;AC=MS:1001309"],
    },
    "characteristics[pooled sample]": {
        "format": "conditional",
        "condition_field": "pooled",
        "when_pooled": {
            "format": "source_names",
            "pattern": "SN=sample1,sample2,...",
            "help": "List source sample names when pooled=true",
        },
    },
    "characteristics[age]": {
        "format": "age_encoding",
        "pattern": "{years}Y{months}M{days}D",
        "examples": ["40Y", "40Y5M", "40Y5M2D", "8W", "40Y-85Y"],
        "help": "Use Y for years, M for months, D for days, W for weeks. Ranges with dash.",
    },
}

# Column mapping - maps SDRF column names to their default value categories
COLUMN_MAPPING = {
    # Required fields
    "technology type": {"type": "single", "values": REQUIRED_SINGLE_VALUES["technology type"]},
    # Replicates
    "characteristics[biological replicate]": {"type": "single", "values": SPECIAL_VALUES["biological_replicate"]},
    "comment[technical replicate]": {"type": "single", "values": SPECIAL_VALUES["technical_replicate"]},
    # Labels
    "comment[label]": {
        "type": "categories",
        "categories": {
            "Label-free": LABEL_VALUES["label free sample"],
            "TMT Labels": LABEL_VALUES["tmt_labels"],
            "SILAC Labels": LABEL_VALUES["silac_labels"],
        },
    },
    # Instruments
    "comment[instrument]": {"type": "single", "values": INSTRUMENT_MODELS},
    # Cleavage agents
    "comment[cleavage agent details]": {
        "type": "structured",
        "format": "key_value",
        "categories": {"Enzymatic": CLEAVAGE_AGENTS["enzymatic"], "Non-enzymatic": CLEAVAGE_AGENTS["non_enzymatic"]},
    },
    # Modifications
    "comment[modification parameters]": {
        "type": "structured",
        "format": "key_value",
        "categories": {
            "Fixed Modifications": PROTEIN_MODIFICATIONS["fixed"],
            "Variable Modifications": PROTEIN_MODIFICATIONS["variable"],
        },
    },
    # Mass tolerances
    "comment[precursor mass tolerance]": {"type": "single", "values": MASS_TOLERANCES["precursor"]},
    "comment[fragment mass tolerance]": {"type": "single", "values": MASS_TOLERANCES["fragment"]},
    # Fragmentation
    "comment[dissociation method]": {"type": "single", "values": FRAGMENTATION_METHODS["dissociation"]},
    "comment[collision energy]": {"type": "single", "values": FRAGMENTATION_METHODS["collision_energy"]},
    # Sample characteristics
    "characteristics[organism]": {"type": "single", "values": SAMPLE_CHARACTERISTICS["organism"]},
    "characteristics[disease]": {"type": "single", "values": SAMPLE_CHARACTERISTICS["disease"]},
    "characteristics[sex]": {"type": "single", "values": SAMPLE_CHARACTERISTICS["sex"]},
    "characteristics[cell type]": {"type": "single", "values": SAMPLE_CHARACTERISTICS["cell_type"]},
    "characteristics[pooled sample]": {"type": "single", "values": SPECIAL_VALUES["pooled_sample"]},
    "characteristics[synthetic peptide]": {"type": "single", "values": SPECIAL_VALUES["synthetic_peptide"]},
    # Sample preparation
    "characteristics[enrichment process]": {"type": "single", "values": SAMPLE_PREPARATION["enrichment_process"]},
    "comment[reduction reagent]": {"type": "single", "values": SAMPLE_PREPARATION["reduction_reagent"]},
    "comment[alkylation reagent]": {"type": "single", "values": SAMPLE_PREPARATION["alkylation_reagent"]},
    "comment[fractionation method]": {"type": "single", "values": SAMPLE_PREPARATION["fractionation_method"]},
    # Data acquisition
    "comment[proteomics data acquisition method]": {"type": "single", "values": DATA_ACQUISITION_METHODS},
    # Fractions
    "comment[fraction identifier]": {"type": "single", "values": SPECIAL_VALUES["fraction_identifier"]},
}


def get_column_defaults(column_name):
    """
    Get default values for a specific SDRF column.

    Args:
        column_name (str): The SDRF column name

    Returns:
        dict: Column default configuration or None if not found
    """
    return COLUMN_MAPPING.get(column_name.lower())


def get_all_column_defaults():
    """
    Get all available column defaults.

    Returns:
        dict: All column mappings
    """
    return COLUMN_MAPPING


def search_columns(query):
    """
    Search for columns containing the query string.

    Args:
        query (str): Search query

    Returns:
        dict: Matching columns and their defaults
    """
    query_lower = query.lower()
    return {col: config for col, config in COLUMN_MAPPING.items() if query_lower in col.lower()}


def get_structured_field_options(column_name, field_type=None):
    """
    Get options for structured fields with key-value pairs.

    Args:
        column_name (str): The SDRF column name
        field_type (str): Optional specific field type for filtering

    Returns:
        dict: Structured field options
    """
    config = get_column_defaults(column_name)
    if not config or config.get("type") != "structured":
        return {}

    if field_type and field_type in config.get("categories", {}):
        return {field_type: config["categories"][field_type]}

    return config.get("categories", {})


def get_compound_field_schema(column_name):
    """
    Get the schema for compound fields that require special handling.

    Args:
        column_name (str): The SDRF column name

    Returns:
        dict: Compound field schema or None if not a compound field
    """
    return COMPOUND_FIELDS.get(column_name.lower())


def get_all_compound_fields():
    """
    Get all compound fields and their schemas.

    Returns:
        dict: All compound field mappings
    """
    return COMPOUND_FIELDS


def validate_compound_field_value(column_name, value):
    """
    Validate a value against a compound field schema.

    Args:
        column_name (str): The SDRF column name
        value (str): The value to validate

    Returns:
        dict: Validation result with 'valid' boolean and 'errors' list
    """
    schema = get_compound_field_schema(column_name)
    if not schema:
        return {"valid": True, "errors": []}

    errors = []

    if schema["format"] == "key_value_pairs":
        # Parse key=value pairs separated by semicolons
        pairs = value.split(schema["separator"])
        found_fields = {}

        for pair in pairs:
            if "=" not in pair:
                errors.append(f"Invalid format: '{pair}' should be key=value")
                continue

            key, val = pair.split("=", 1)
            found_fields[key] = val

        # Check required fields
        for field_name, field_config in schema["fields"].items():
            if field_config.get("required") and field_name not in found_fields:
                errors.append(f"Missing required field: {field_name}")
            elif field_name in found_fields and field_config.get("options"):
                if found_fields[field_name] not in field_config["options"]:
                    errors.append(f"Invalid value for {field_name}: {found_fields[field_name]}")

    return {"valid": len(errors) == 0, "errors": errors}


def get_column_suggestions(partial_name):
    """
    Get column name suggestions based on partial input.

    Args:
        partial_name (str): Partial column name

    Returns:
        list: List of matching column names
    """
    partial_lower = partial_name.lower()
    suggestions = []

    for column in COLUMN_MAPPING.keys():
        if partial_lower in column.lower():
            suggestions.append(column)

    return sorted(suggestions)


def get_quick_values(category):
    """
    Get quick access to commonly used value categories.

    Args:
        category (str): Value category (labels, instruments, organisms, etc.)

    Returns:
        dict: Category values or error
    """
    quick_access = {
        "labels": {
            "tmt": LABEL_VALUES["tmt_labels"],
            "silac": LABEL_VALUES["silac_labels"],
            "label_free": LABEL_VALUES["label free sample"],
        },
        "instruments": INSTRUMENT_MODELS,
        "organisms": SAMPLE_CHARACTERISTICS["organism"],
        "diseases": SAMPLE_CHARACTERISTICS["disease"],
        "cell_types": SAMPLE_CHARACTERISTICS["cell_type"],
        "data_acquisition": DATA_ACQUISITION_METHODS,
        "fragmentation": FRAGMENTATION_METHODS["dissociation"],
        "replicates": {
            "biological": SPECIAL_VALUES["biological_replicate"],
            "technical": SPECIAL_VALUES["technical_replicate"],
        },
    }

    return quick_access.get(category)

default_columns = [{
            "name": "Source name", "type": "", "mandatory": True
        },
            {
            "name": "Organism", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Tissue", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Disease", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Cell type", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Biological replicate", "type": "Characteristics", "mandatory": True
        },{
            "name": "Material type", "type": "", "mandatory": True
        },
            {
                "name": "Assay name", "type": "", "mandatory": True
        }, {
            "name": "Technology type", "type": "", "mandatory": True
        },  {
                "name": "Technical replicate", "type": "Comment", "mandatory": True
            },
            {"name": "Label", "type": "Comment", "mandatory": True},
            {"name": "Fraction identifier", "type": "Comment", "mandatory": True},
            {"name": "Instrument", "type": "Comment", "mandatory": True},
            {"name": "Data file", "type": "Comment", "mandatory": True},
            {"name": "Cleavage agent details", "type": "Comment", "mandatory": True},
            {"name": "Modification parameters", "type": "Comment", "mandatory": True},
            {"name": "Dissociation method", "type": "Comment", "mandatory": True},
            {"name": "Precursor mass tolerance", "type": "Comment", "mandatory": True},
            {"name": "Fragment mass tolerance", "type": "Comment", "mandatory": True},
        ]

user_metadata = [
            {
                "name": "Source name", "type": "", "mandatory": True
            },
            {
                "name": "Organism", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Tissue", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Cell type", "type": "Characteristics", "mandatory": False
            },
            {
                "name": "Reduction reagent", "type": "Comment", "mandatory": False
            }
            ,
            {
                "name": "Alkylation reagent", "type": "Comment", "mandatory": False
            },
{
        "name": "Sex", "type": "Characteristics", "mandatory": True
    },
    {
        "name": "Developmental stage", "type": "Characteristics", "mandatory": True
    },
    {
        "name": "Age", "type": "Characteristics", "mandatory": True
    },
{
      "name": "Mass", "type": "Characteristics","mandatory": True
    },
            {
              "name": "Assay name", "type": "", "mandatory": True, "value": "run 1", "hidden": True, "auto_generated": True
            },
            {
                "name": "Technology type", "type": "", "mandatory": True, "value": "proteomic profiling by mass spectrometry", "hidden": True
            },
            {
                "name": "Technical replicate", "type": "Comment", "mandatory": True, "value": "1"
            },
            {
                "name": "Biological replicate", "type": "Comment", "mandatory": True, "value": "1"
            }
            ,
            {
                "name": "Sample type", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Enrichment process", "type": "Characteristics", "mandatory": True
            }
            ,
            {
                "name": "Cleavage agent details", "type": "Comment", "mandatory": True
            },


    {
        "name": "Modification parameters", "type": "Comment", "mandatory": True
    }

        ]

staff_metadata = [
            {
                "name": "Data file", "type": "Comment", "mandatory": True
            },
            {
                "name": "File uri", "type": "Comment", "mandatory": True
            },
            {
                "name": "Proteomics data acquisition method", "type": "Comment", "mandatory": True
            }
            ,
            {
                "name": "Label",
                "type": "Comment",
                "mandatory": True
            },
            {
                "name": "MS1 scan range", "type": "Comment", "mandatory": True
            },
{
        "name": "Instrument", "type": "Comment", "mandatory": True, "hidden": True
    },
            {
                "name": "MS2 analyzer type", "type": "Comment", "mandatory": True, "hidden": True
            },

    {"name": "Dissociation method", "type": "Comment", "mandatory": True},
    {"name": "Precursor mass tolerance", "type": "Comment", "mandatory": True},
    {"name": "Fragment mass tolerance", "type": "Comment", "mandatory": True},
        ]
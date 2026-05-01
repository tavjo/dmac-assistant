# Using SEEK and NExtSEEK

An explanation of the major concepts and major pages of the SEEK/NExtSEEK data management platform

## [hashtag](#page-pAI16oJkAoPmL8VBz5OF-concepts) Concepts:

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-seek-vs-nextseek) SEEK vs NExtSEEK

NExtSEEK is a modified wrapped, built on top of the SEEK infrastructure. The fundamental differences that differentiate the SEEK and NExtSEEK platforms are outlined in the  Although there are differences, SEEK is required for NExtSEEK's functionality, as we leverage and use many features from the core SEEK. All data/metadata in NExtSEEK are compatible with SEEK. This compatibility is shown by using , an instance of the core SEEK infrastructure, as the metadata repository we use to publish our research data. An example of published research data exists

SEEK and NExtSEEK are utilized together, each serving different purposes. Below is a very brief explanation of how the two platforms interact.

Core SEEK:
- Functionality: Register for accounts (same account used for SEEK and NExtSEEK), create Projects/SampleTypes/Assays, administer account-project associations

NExtSEEK:
- Functionality: Upload/Search/Download Samples, Protocols, and Data Files

We use SEEK as the administrative site (creating assets and administering roles), while NExtSEEK is used for all things data (uploading, downloading, searching).

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-isa-structure) ISA Structure

SEEK/NExtSEEK uses the ISA metadata tracking framework as described . ISA = Investigation, Study, Assay. In our case: Investigation = Grant/Research Project, Study = Publication, and Assay = Experiment. This is a nested structure -> There are multiple Assays in a Study, and multiple Studies in an Investigation.

This is how the data is modeled in the public domain (on FAIRDOMHub), but in the scope of NExtSEEK, we treat the investigation and study as a singular node. During the research process, it's often unknown which data will be part of a particular publication, therefore, all data of ongoing research efforts (on NExtSEEK), lives underneath a single study. When data is published from NExtSEEK to FAIRDOMHub, it is then associated with a publication, and can then be in ISA format.

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-types-of-assets) Types of Assets

SEEK/NExtSEEK has a few different flavors/types of assets: Samples, Assays, Protocols, and Data Files.

#### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-samples) **Samples:**

A sample is any unit of biological, chemical, or data material that is subject to analysis or experimentation. It can range from a tangible entity, such as a patient or tissue specimen, to digital data outputs like raw or analyzed sequencing data files.

Samples are stored as tabular metadata **(excel)**, and grouped into different Sample Types; each describing a specific type of data or metadata. Each sample type is unique and will contain a different subset of attributes. Some attributes are shared, such as UUID (unique identifier/primary key), Name (also needs to be unique), Protocol (A field that links to the protocol associated with the sample), Parent (unique identifier of Parent sample), and more.
Sample Type Nomenclature: Samples without a prefix = Metadata samples. D.XXX = Data File, A.XXX = Analyzed Data File.
*Examples: PAT: Human Patient, TIS: Tissue, DNA: DNA Library, D.SEQ: Sequencing File, A.GEX: Gene Expression Analysis File.*

#### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-assays) **Assays:**

An Assay is a type of experiment/procedure done on a Sample, to generate another sample. These can be broad terms, or more specific. Assays always have two samples associated with them: the Parent sample that feeds into the assay, and the Child sample that is generated from the assay.
*Examples: PAT -> Tissue Collection -> TIS -> DNA Extraction -> DNA -> Short Read Sequencing -> D.SEQ -> Gene Expression Analysis -> A.GEX*

In the above example, the PAT sample feeds into the Tissue Collection Assay and generates a TIS sample.

Assays are Study specific. To view the full list of assays that are visible to you, head  To view the list of assays associated with a study, head to the  for your specific project.

#### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-protocols) **Protocols:**

A description of the assay/experiment performed on the sample. Can be in any format (PDF, DOCX, XLSX, TXT, IMG, etc). Ideally, this is primary materials from a lab (primary protocols used in-house), but materials and methods sections usually suffice.
*Examples: Protocols describing* *, DNA Library Creation,* *, and* *. Again, these can be Word documents, PDFs, text files, etc.*

#### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-data-files) **Data Files:**

An actual data file. Not frequently used. We are not looking to house/manage terabytes of research data, nor be responsible for serving/housing that data to the public (in perpetuity). Instead, we push for data to live in their respective repositories, and until then, in their original home (generating lab). We can store data files on SEEK/NExtSEEK, and those data files can be downloaded by users who have access, but the majority of our use cases point to systems that are much better at managing data transfers (repositories, cloud computing environments, Globus, etc).

## [hashtag](#page-pAI16oJkAoPmL8VBz5OF-pages-on-nextseek) Pages on NExtSEEK:

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-data-entry) Data Entry

There are three pages associated with Data Entry:

* : Where a user uploads samples
* : Where a user uploads data files/protocols
* : Housing sample sheet templates for users to use (to prep and upload files)

More information on how to use these pages exists on the  page.

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-data-query) Data Query

There are four pages associated with Data Query:

* Advanced Search: A text search of the entire database (all samples). Allows complex searching (AND/OR/NOT). partial/exact matches, and sample type specificity.
* Simple Search: Search a single Sample Type, by a single Attribute, by a single Value.
  *Example: All D.SEQ whose Type contains 'RNA-Seq'*
* Data File Query: Search through what data files exist in a filterable table. Files are downloadable as well (single + batch).

More information on how to search / download samples exists on the  page.

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-sample-pages) Sample Pages

Each sample has its own page on NExtSEEK located at: XXX (where XXX = the UUID of that sample).

The sample page has two sections: An interactive Sample Tree and a table of Metadata.

The interactive sample tree shows all connected Parent/Child samples. By clicking on a sample, you then load the sample page of that sample.

The table of Metadata is straightforward - it is the metadata associated with that sample.

Sample pages can take some time to load (as they are not all stored in the database, and are auto-generated on load)- depending on the number of nodes (child/parent) associated with the sample.

## [hashtag](#page-pAI16oJkAoPmL8VBz5OF-pages-on-seek) Pages on SEEK:

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-account-registration-project-association) Account Registration / Project Association:

Accounts are registered on the SEEK website (and then used on both the SEEK and NExtSEEK websites). You can register for an account here: .

Once you have an account, you will need to be approved and added to a project (by an administrator) to access SEEK/NExtSEEK. This is what federates access to different Projects, and therefore access to the different assets of those projects. You must be a member of a project to access the assets, therefore allowing multiple projects to exist in the same database.

To administer project associations: .

You can also request to join a project: .

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-creating-assets-sample-types-assays-projects) Creating Assets (Sample Types, Assays, Projects)

To create a new asset type, the SEEK website is used. Whether that is creating a new Sample Type, a new Assay, or creating a new Project.

Documentation surrounding creating these assets can be found directly on the SEEK Documentation, linked below:

* Assay: There is no documentation on the SEEK website for this.

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-clades) Clades

To organize and standardize the various types of samples in our system, we have defined a four-tiered structure known as Clades. Each clade represents a distinct level in the data generation and processing lifecycle, enabling better metadata classification and downstream tracking.

**1. Source Clade**

* **Definition**: Primary metadata-only samples that represent biological sources.
* **Examples**: Patients, Antibodies, Non-Human Primates (NHP), Mice.
* **Purpose**: Serve as the origin point for all derived experimental materials.

**2. Processed Clade**

* **Definition**: Samples or materials derived from Source clade samples.
* **Examples**: Cells, Tissues, DNA, RNA.
* **Purpose**: Represent physical biomaterials used in experimental assays.

**3. Raw Clade**

* **Definition**: Unprocessed output data generated from assays run on Processed samples.
* **Examples**: Sequencing reads, raw imaging files, flow cytometry data.
* **Notation**: Denoted by a **D** (for "Data").

**4. Analyzed Clade**

* **Definition**: Final processed or interpreted data outputs derived from Raw data.
* **Examples**: Gene expression matrices, statistical summaries, differential analysis results.
* **Notation**: Denoted by an **A** (for "Analyzed").

### [hashtag](#page-pAI16oJkAoPmL8VBz5OF-seek-documentation-link) SEEK Documentation Link

A link to the full SEEK Documentation exists here:  (head to user guides).


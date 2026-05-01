# Uploading

An in depth overview of how to upload Samples, Protocols, and Data Files to NExtSEEK

## [hashtag](#page-uGmao2ozEsJNYeIt3klZ-uploading-samples) Uploading Samples

### [hashtag](#page-uGmao2ozEsJNYeIt3klZ-excel-sheet-structure) Excel Sheet Structure

Samples are tabular metadata and are uploaded to the database as Excel sheets. These Excel sheets must be structured in a specific format to be successfully uploaded.

Properly formatted Upload Sheets have four sub-sheets: **Instructions, Samples, Ontology, and Assay.**

**Instructions:** This sheet contains all of the information required to add the sample to the Database. There are four required columns in this sheet: *Field, Database Field, Field Type, and Ontology.*
*Field* = An identical match to the headers of the Samples Page. The headers/column names do **NOT** need to be the database name of the attribute.
*Database Field* = Formatted as SAMPLETYPE::Attribute Name -> Ex: TIS::Type or D.SEQ::Name. The Attribute name here **MUST** exactly match the exact DB Field Name. This maps the value in the Samples sheet to the correct Attribute.
*Field Type* = Text, Number, Date, Controlled Ontology
*Ontology* = If Field Type == Controlled Ontology, the name of the Ontology (in the Ontology) sheet.

**Samples**: This is the table of metadata, where each row is a sample, and each column is an attribute for that sample. The column headers (Row 1) are the attribute names, and must identically match the *Field* column (transposed) of the Instructions page.

* For samples, Name and File\_Primary Data must be unique (per sample type). There cannot be two samples in the database with the same Name or File\_PrimaryData (per sample type)

**Ontology:** This sheet contains ontologies (sets of controlled vocabulary terms) that can be used to control the values of an attribute. For an ontology to be enforced, the "Field Type" on the Instructions page for that attribute must be set to "Controlled Ontology", and the name of the Ontology (header in the Ontology sheet) must be set as the "Ontology" of that attribute on the Instructions Page. See the image below for more clarification.

**Assay:** This sheet determines which Assay(s) the uploaded samples should be associated with. The required columns are: SampleType, AssayType, Assay, Direction.

Attached is an example sample sheet, with notes/annotations as described above.

### [hashtag](#page-uGmao2ozEsJNYeIt3klZ-assay-sheet-sample-sheet-and-update-sheets) Assay Sheet, Sample Sheet, and Update Sheets

There are three different types of upload sheets: Assay Sheets, Sample Sheets, and Update Sheets.

* Assay Sheets / Sample Sheets follow the Excel Sheet Format as shown above.

  + Assay/Sample Sheets must be used to upload a sample for the first time, to generate the UID.

    - The first time you upload an Assay/Sample Sheet, the UID column should be blank and will be automatically generated. Following upload, paste the UIDs into your upload sheet from the auto-generated feedback sheet.

Below are examples of an Assay Sheet / Update Sheet. An Example of a Sample Sheet is linked above (SampleSheetFormatting\_Template\_240824.xlsx)

### [hashtag](#page-uGmao2ozEsJNYeIt3klZ-sample-validation-script) Sample Validation Script

Once you have formatted your Assay/Sample Sheet for Upload, there exists a Sample Validation Script on the  page to check that the sheet is in the correct format.

Choose your prepared Assay/Sample Sheet (*not applicable for update sheets*) and click validate.

The validation script checks:

* That the Excel sheet is formatted correctly (Instructions, Samples, Ontology, Assay)
* That the Instructions Page is formatted correctly (Field, Database Field, Field Type, Ontology)

  + In the above example, the Ontology column is missing

Not all of these errors would cause the upload to error out. Any error with the overall structure/format of the sheet would cause an upload to fail. A mislabeled attribute is not going to cause an error, but will instead upload that sample WITHOUT that attribute.

It is **good practice** to test your sample sheet on sample validation before uploading.

### [hashtag](#page-uGmao2ozEsJNYeIt3klZ-how-to-upload) How to Upload

1. Once you have created your assay or sample sheet, head to the
2. Submit your sheet through Sample Validation.
3. Following validation success, place your sheet in the upload box. If you are an admin, select which lab/user you are uploading for. If not, leave as default and it will upload as yourself.

1. Click Upload. Should take around 1 second per sample

   1. To track your upload, head to either Search Page **(INSERT LINK).** Search today's date in YYMMDD format (so 8/23/24 = 240823).
   2. Through running that search a few times, you should see the number of samples increasing, therefore tracking that your upload is running successfully.

## [hashtag](#page-uGmao2ozEsJNYeIt3klZ-uploading-protocols-data-files) Uploading Protocols / Data Files

To upload Protocols and Data Files, head to the.

1. Select whether the file(s) you are uploading are Data Files or Protocols
2. If you are an admin, select which Lab/User you are uploading for. If you are not, leave it as the default
3. Place the files into the "File Dropzone" and click submit. Wait for data files/protocols to be uploaded

For Protocols, following the procedure above is sufficient to upload.

Data Files require a Sample with a File\_PrimaryData that == the name of the file you are trying to upload (to automatically match the Data File UID / Link\_PrimaryData to the corresponding samples). If there is not a D. Sample that matches your data file name, you can make a D.FILE sample to trick the system into uploading it- this is particularly useful when the file you are trying to associate is not a primary file, but a supplementary data file, such as a FASTQC.html. Below is a D.FILE\_Template.

#### [hashtag](#page-uGmao2ozEsJNYeIt3klZ-documentation-surrounding-globus-uploading-and-downloading-exists-here) Documentation surrounding Globus (Uploading and Downloading) exists


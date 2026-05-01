# Useful Links

SEEK: [https://seek4science.org/arrow-up-right](https://seek4science.org/) or [https://fairdata.mit.edu/arrow-up-right](https://fairdata.mit.edu/)

SEEK Documentation: [https://docs.seek4science.org/arrow-up-right](https://docs.seek4science.org/)

NExtSEEK: [https://nextseek.mit.edu/arrow-up-right](https://nextseek.mit.edu/)

SEEK/NExtSEEK Installation: [https://igb.mit.edu/data-management/seek-and-nextseekarrow-up-right](https://igb.mit.edu/data-management/seek-and-nextseek)

FAIRDOMHub: [https://fairdomhub.org/arrow-up-right](https://fairdomhub.org/)

Repositories:

* Sequence Read Archive:
* Gene Expression Omnibus:
* Zenodo:
* Immport:
* MIT.OMERO:
* PRIDE:

[https://www.ncbi.nlm.nih.gov/sraarrow-up-right](https://www.ncbi.nlm.nih.gov/sra)

[https://www.ncbi.nlm.nih.gov/geo/arrow-up-right](https://www.ncbi.nlm.nih.gov/geo/)

[https://zenodo.org/arrow-up-right](https://zenodo.org/)

[https://www.dev.immport.org/homearrow-up-right](https://www.dev.immport.org/home)

[https://omero.mit.edu/webclient/arrow-up-right](https://omero.mit.edu/webclient/)

[https://www.ebi.ac.uk/pride/arrow-up-right](https://www.ebi.ac.uk/pride/)

If you try and update an already registered sample without its UID, the system will not allow it. It will think you are trying to upload a new sample, but then throw an error because a sample with that name already exists.

- When using an Assay / Sample Sheet to update samples-> **All attributes** for that sample must be included. If an attribute is not included at a later update, that metadata will be removed from the sample.

- An Assay Sheet contains multiple sample types, while a Sample Sheet contains a single sample type.

- Update Sheets are used to *update* a subset of attributes for a sample that has already been uploaded. UID's must be included, and the attribute header must match the database name.

That the entries of Database Field match attributes in the database

* In the above example, sample type CEL does not have the attribute Protocols (it should be Protocol)

- That the Header row in the Samples page == Field column in the Instructions page

  * Disregard the 'Field' error, but in the above example, it's finding that there exists an entry in the Instructions page for Source, that does not exist in the Samples page.

- That the Assay Sheet is formatted correctly (SampleType, AssayType, Assay, Direction)

  * In the above example, the column AssayType is missing, and there is an extra column named "1"

Following upload, paste your generated UIDs from the feedback file back into your upload sheet

- IMPORTANT: Quality checks

  1. Check a few samples
  2. Ensure that the correct # of samples got uploaded
  3. Ensure that all attributes for your samples are uploaded.

The resulting UID generated in the bottom table will be the UID used to reference that Data File or Protocol. Data File UIDs are SampleTypeUID\_FileName. Protocol UIDs are P.LAB-YYMMDD\_Version\_FileName

file-download

17KB

[SampleSheetFormatting\_Template\_240824.xlsx](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/vjOCsCt32ahoFFD9AFhF/SampleSheetFormatting_Template_240824.xlsx?alt=media&token=c3a0a80c-0684-4f46-9d5e-82d3a2ae3eeb)

downloadDownload[arrow-up-right-from-squareOpen](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/vjOCsCt32ahoFFD9AFhF/SampleSheetFormatting_Template_240824.xlsx?alt=media&token=c3a0a80c-0684-4f46-9d5e-82d3a2ae3eeb)

A SampleSheet Template Upload Sheet with some extra notes, as explained above

file-download

15KB

[AssaySheet\_Template\_240824.xlsx](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/W6WNAvhu9UuPfkLfFSlt/AssaySheet_Template_240824.xlsx?alt=media&token=2d6caa11-67ba-4f38-b967-dda525adafa4)

downloadDownload[arrow-up-right-from-squareOpen](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/W6WNAvhu9UuPfkLfFSlt/AssaySheet_Template_240824.xlsx?alt=media&token=2d6caa11-67ba-4f38-b967-dda525adafa4)

This AssaySheet will upload 12 NHP's and 12 TIS's (each of them automatically associated with those NHPs).

file-download

11KB

[UpdateSheet\_Template\_240824.xlsx](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/7Hht8abgsM9TjqE4omwh/UpdateSheet_Template_240824.xlsx?alt=media&token=5c146b10-8dfe-4f28-9c43-b541b21305dc)

downloadDownload[arrow-up-right-from-squareOpen](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/7Hht8abgsM9TjqE4omwh/UpdateSheet_Template_240824.xlsx?alt=media&token=5c146b10-8dfe-4f28-9c43-b541b21305dc)

This update sheet will only update the two attributes listed (Sex and DateOfBirth) for those 12 NHPs

[Uploadingarrow-up-right](https://nextseek.mit.edu/seek/samples/upload/)

[Uploading Pagearrow-up-right](https://nextseek.mit.edu/seek/samples/upload/)

[Protocol/Data File Uploading Pagearrow-up-right](https://nextseek.mit.edu/seek/data/upload/)

file-download

14KB

[D.FILE\_Template\_240824.xlsx](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/RBh1oRAmdKSMOKgzCwnu/D.FILE_Template_240824.xlsx?alt=media&token=206a6df6-13e9-4d73-914f-79786c5cb98f)

downloadDownload[arrow-up-right-from-squareOpen](https://307762428-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces/LyjMyzUsC7E9wbJHwIA3/uploads/RBh1oRAmdKSMOKgzCwnu/D.FILE_Template_240824.xlsx?alt=media&token=206a6df6-13e9-4d73-914f-79786c5cb98f)

[here:](#page-7baNS1Y1qblWsOaQp2lJ-globus)

![](https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/image?url=https%3A%2F%2F307762428-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FLyjMyzUsC7E9wbJHwIA3%252Fuploads%252FboudTqYSZEHDxBtXkVSW%252Fimage.png%3Falt%3Dmedia%26token%3Def23a3d7-eebf-4632-a8c3-dcfb81747772&width=768&dpr=3&quality=100&sign=b380e0b4&sv=2)

Visual Representation of sheets as explained above

![](https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/image?url=https%3A%2F%2F307762428-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FLyjMyzUsC7E9wbJHwIA3%252Fuploads%252FfCiLJu0Arygw4jV1pZYi%252Fimage.png%3Falt%3Dmedia%26token%3D93d9f01e-5840-4e72-ba5b-3aa617b8d7f3&width=768&dpr=3&quality=100&sign=d85231c9&sv=2)

Sample Validation Check on the Upload Page

![](https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/image?url=https%3A%2F%2F307762428-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FLyjMyzUsC7E9wbJHwIA3%252Fuploads%252FzufVp5xK354F4bGDV13b%252Fimage.png%3Falt%3Dmedia%26token%3D6de87dba-986b-4db9-b568-967b8b8c6e45&width=768&dpr=3&quality=100&sign=cfe29e97&sv=2)

Logging output function that shows what the validation check looks for

![](https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/image?url=https%3A%2F%2F307762428-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FLyjMyzUsC7E9wbJHwIA3%252Fuploads%252FzITrGHiHZZEvPGcycwXW%252Fimage.png%3Falt%3Dmedia%26token%3D910af84b-7b19-48ea-aaf5-b9ab263d53cd&width=768&dpr=3&quality=100&sign=d49625f&sv=2)

Sample Uploading Box

![](https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/image?url=https%3A%2F%2F307762428-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FLyjMyzUsC7E9wbJHwIA3%252Fuploads%252FzjRbBMASwuyV9OdAWVqH%252Fimage.png%3Falt%3Dmedia%26token%3D1b15a75d-c9f6-484d-9417-c9d2b59fde02&width=768&dpr=3&quality=100&sign=e6647aff&sv=2)

Protocol / Data File Uploading page


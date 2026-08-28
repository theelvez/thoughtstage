# Researcher-created experiments

The local experiment-builder wizard writes each validated study into its own
subdirectory here. A generated workspace contains `experiment.yaml` and, when
provided, a confined `files/` directory of UTF-8 research materials.

Generated studies are ordinary Thoughtstage experiments: review them, validate
them with the CLI, and commit the ones intended for publication. The builder
never stores credential values; it records environment-variable names only.

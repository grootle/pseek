use ignore::WalkBuilder;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::path::PathBuf;


#[pyclass]
struct IgnoreMatcher {
    matcher: ignore::IncrementalIgnore
}


#[pymethods]
impl IgnoreMatcher {
    #[new]
    fn new(root: String) -> PyResult<Self> {
        let root = PathBuf::from(root);

        let mut builder = WalkBuilder::new(&root);

        builder
            .standard_filters(false)

            // hidden files aren't ignored
            .hidden(false)

            // .gitignore
            .git_ignore(true)

            // .git/info/exclude
            .git_exclude(true)

            // global gitignore
            .git_global(true)

            // .ignore
            .ignore(true)

            // parent ignore files
            .parents(true)

            // Require an actual git repository for git-related
            // ignore rules.
            .require_git(true);

        let mut matchers = builder.build_matchers();

        let matcher = matchers
            .pop()
            .ok_or_else(|| {
                PyRuntimeError::new_err(
                    "failed to create ignore matcher"
                )
            })?;

        Ok(Self { matcher })
    }


    fn is_ignored(
        &mut self,
        path: String,
        is_dir: bool,
    ) -> PyResult<bool> {
        let path = PathBuf::from(path);

        let relative = self
            .matcher
            .normalize(&path)
            .ok_or_else(|| {
                PyRuntimeError::new_err(
                    "path is outside the ignore root"
                )
            })?;

        Ok(
            self.matcher
                .matched(&relative, is_dir)
                .is_ignore()
        )
    }
}


#[pymodule]
fn _pignore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<IgnoreMatcher>()?;
    Ok(())
}

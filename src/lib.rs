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
    #[pyo3(signature = (
        root,
        git_ignore=true,
        git_exclude=true,
        git_global=true,
        ignore=true,
        parents=true,
        require_git=true
    ))]
    fn new(
        root: String,
        git_ignore: bool,
        git_exclude: bool,
        git_global: bool,
        ignore: bool,
        parents: bool,
        require_git: bool
    ) -> PyResult<Self> {
        let root = PathBuf::from(root);

        let mut builder = WalkBuilder::new(&root);

        builder
            .standard_filters(false)

            // hidden files aren't ignored.
            // The logic for filtering hidden paths is implemented in Python
            .hidden(false)

            // .gitignore
            .git_ignore(git_ignore)

            // .git/info/exclude
            .git_exclude(git_exclude)

            // global gitignore
            .git_global(git_global)

            // .ignore
            .ignore(ignore)

            // parent ignore files
            .parents(parents)

            // Require an actual git repository for git-related
            // ignore rules.
            .require_git(require_git);

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

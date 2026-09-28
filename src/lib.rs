use ignore::overrides::OverrideBuilder;
use ignore::WalkBuilder;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use std::path::PathBuf;


#[pyclass]
struct IgnoreMatcher {
    matcher: ignore::IncrementalIgnore,
    has_positive_globs: bool
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
        require_git=true,
        hidden=true,
        globs=None,
        glob_root=None
    ))]
    fn new(
        root: String,
        git_ignore: bool,
        git_exclude: bool,
        git_global: bool,
        ignore: bool,
        parents: bool,
        require_git: bool,
        hidden: bool,
        globs: Option<Vec<String>>,
        glob_root: Option<String>,
    ) -> PyResult<Self> {
        let root = PathBuf::from(root);

        // Use a separate base for glob patterns when provided
        let glob_root = glob_root
            .map(PathBuf::from)
            .unwrap_or_else(|| root.clone());

        let mut builder = WalkBuilder::new(&root);

        builder
            .standard_filters(false)

            // Hidden paths (those starting with a dot)
            .hidden(hidden)

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

        let mut has_positive_globs = false;

        // Add command-line glob overrides
        if let Some(globs) = globs {
            let mut overrides = OverrideBuilder::new(&glob_root);

            for glob in &globs {
                overrides.add(glob).map_err(|e| {
                    PyValueError::new_err(format!(
                        "Invalid glob pattern {glob:?}: {e}"
                    ))
                })?;
            }

            let overrides = overrides.build().map_err(|e| {
                PyValueError::new_err(format!(
                    "Failed to build glob matcher: {e}"
                ))
            })?;

            // Check whether at least one positive glob was provided
            has_positive_globs = overrides.num_whitelists() > 0;

            builder.overrides(overrides);
        }

        let mut matchers = builder.build_matchers();

        let matcher = matchers
            .pop()
            .ok_or_else(|| {
                PyRuntimeError::new_err(
                    "failed to create ignore matcher"
                )
            })?;

        Ok(Self { matcher, has_positive_globs })
    }

    #[getter]
    fn has_positive_globs(&self) -> bool {
        self.has_positive_globs
    }

    fn match_path(
        &mut self,
        path: String,
        is_dir: bool,
    ) -> PyResult<(bool, bool, bool)> {
        let path = PathBuf::from(path);

        let relative = self
            .matcher
            .normalize(&path)
            .ok_or_else(|| {
                PyRuntimeError::new_err(
                    "path is outside the ignore root"
                )
            })?;

        let matched = self.matcher.matched(&relative, is_dir);

        Ok((
            matched.is_ignore(),
            matched.is_whitelist(),
            matched.should_descend()
        ))
    }
}


#[pymodule]
fn _pignore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<IgnoreMatcher>()?;
    Ok(())
}

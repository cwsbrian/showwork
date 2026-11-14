fn main() {
    let revision = std::env::var("GITHUB_SHA").ok().or_else(|| {
        std::process::Command::new("git")
            .args(["rev-parse", "HEAD"])
            .current_dir("../..")
            .output()
            .ok()
            .filter(|output| output.status.success())
            .and_then(|output| String::from_utf8(output.stdout).ok())
            .map(|output| output.trim().to_string())
    }).unwrap_or_else(|| "unknown".into());
    println!("cargo:rustc-env=SHOWWORK_BUILD_REVISION={revision}");
    println!("cargo:rerun-if-env-changed=GITHUB_SHA");
    println!("cargo:rerun-if-changed=../../.git/HEAD");
    tauri_build::build()
}

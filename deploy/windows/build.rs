#[cfg(target_os = "windows")]
fn main() {
    println!("cargo:rerun-if-changed=assets/icons/app.ico");
    winresource::WindowsResource::new()
        .set_icon("assets/icons/app.ico")
        .compile()
        .expect("Windowsのアイコンを埋め込めません。");
}

#[cfg(not(target_os = "windows"))]
fn main() {}

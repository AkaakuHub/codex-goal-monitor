use std::{path::PathBuf, sync::Arc};

use anyhow::Result;
use tray_icon::menu::MenuEvent;

use super::{App, Event};
use crate::config::Settings;

pub fn run(settings: Settings, path: PathBuf) -> Result<()> {
    use tao::{
        event::{Event as NativeEvent, StartCause},
        event_loop::{ControlFlow, EventLoopBuilder},
    };
    let event_loop = EventLoopBuilder::<Event>::with_user_event().build();
    #[cfg(target_os = "macos")]
    let event_loop = {
        use tao::platform::macos::{ActivationPolicy, EventLoopExtMacOS};
        let mut event_loop = event_loop;
        event_loop.set_activation_policy(ActivationPolicy::Accessory);
        event_loop.set_dock_visibility(false);
        event_loop
    };
    let proxy = event_loop.create_proxy();
    let send = Arc::new(move |event| {
        let _ = proxy.send_event(event);
    });
    let menu = send.clone();
    MenuEvent::set_event_handler(Some(move |event| menu(Event::Menu(event))));
    let mut app = None;
    event_loop.run(move |event, _, control| {
        *control = ControlFlow::Wait;
        match event {
            NativeEvent::NewEvents(StartCause::Init) => {
                match App::new(settings.clone(), path.clone(), send.clone()) {
                    Ok(created) => app = Some(created),
                    Err(error) => {
                        tinyfiledialogs::message_box_ok(
                            "起動できません",
                            &error.to_string(),
                            tinyfiledialogs::MessageBoxIcon::Error,
                        );
                        *control = ControlFlow::Exit;
                    }
                }
            }
            NativeEvent::UserEvent(event) => {
                if app.as_mut().is_some_and(|app| app.event(event)) {
                    *control = ControlFlow::Exit;
                }
            }
            _ => {}
        }
    });
}

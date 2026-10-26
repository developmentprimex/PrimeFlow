# Buttons

Use `Button` for actions and `Button asChild` with a link for navigation that looks like an action.

- Shape: 8px corners for actions, tabs, filters, icon buttons and select triggers.
- Groups: mark the surrounding container with `data-slot="button-group"`; its 12px corners follow the 4px inset around the buttons. Shared `TabsList` uses the same rule.
- Sizes: `sm` / `icon-sm` = 32px, default / `icon` = 36px, `lg` / `icon-lg` = 40px.
- Variants: default for the main action, outline for secondary actions, destructive for deletion, ghost for quiet icon actions, link for text actions.
- Keep existing compact dimensions in dense tables and project cards; use the shared shape and focus treatment.
- Reserve `data-button-shape="circle"` for avatar triggers. Checkboxes, radios and switches retain their own shapes.

Tokens and compatibility rules live in `src/app/button-system.css`. The shape rule also covers legacy native buttons and `.btn-*` links, so local `rounded-*` classes cannot introduce another button style. Keep semantic colors and disabled states. The rules apply on screen and do not override print layouts.

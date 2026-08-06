; Rust tags query — version-matched to tree-sitter-rust 0.24.x

(function_item
  name: (_) @name
) @definition.function

(struct_item
  name: (_) @name
) @definition.type

(enum_item
  name: (_) @name
) @definition.type

(trait_item
  name: (_) @name
) @definition.interface

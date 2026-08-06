; Python tags query — version-matched to tree-sitter-python 0.25.x
; (async def и декораторы парсятся как function_definition/decorated_definition
;  с вложенным function_definition — они захватываются правилом ниже)

(function_definition
  name: (_) @name
) @definition.function

(class_definition
  name: (_) @name
) @definition.class

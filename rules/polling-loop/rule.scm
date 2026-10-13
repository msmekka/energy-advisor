; rules/polling-loop/rule.scm
((while_statement
    condition: (comparison_operator)
    body: (block
        (expression_statement
            (call
                function: (attribute
                            object: (identifier) @_module
                            attribute: (identifier) @_func)
                arguments: (argument_list
                            [(float) (integer)] @interval)))))

    @polling_loop

    (#eq? @_module "time")
    (#eq? @_func "sleep"))

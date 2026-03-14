import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { PersonaInfo } from "@/types/api";

interface PersonaCardProps {
  name: string;
  persona: PersonaInfo;
}

export function PersonaCard({ name, persona }: PersonaCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span className="flex size-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">
            {name.slice(0, 2).toUpperCase()}
          </span>
          {persona.name}
          <Badge variant="secondary">{persona.role}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm text-muted-foreground">{persona.description}</p>
        <div className="flex flex-wrap gap-1">
          {persona.tools.map((tool) => (
            <Badge key={tool} variant="outline" className="text-xs">
              {tool}
            </Badge>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Model: {persona.model}
        </p>
      </CardContent>
    </Card>
  );
}
